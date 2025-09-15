import json
import time
from typing import Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.schemas.openai import (
    ChatCompletionRequest, 
    ResponsesRequest,
    ErrorResponse
)
from app.services.provider import get_provider_adapter, ProviderError
from app.services.logging import get_logging_service
from app.services.rate_limiter import check_rate_limit
from app.services.monitoring import metrics_collector
from app.core.security import hash_api_key
from app.models.models import ApiKey
from app.core.config import get_config_manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible API"])
security = HTTPBearer()

async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> int:
    """Verify API key and return the API key ID"""
    token = credentials.credentials
    
    try:
        # First check if token matches any configured key
        config_manager = get_config_manager(db)
        proxy_key = config_manager.get("PROXY_KEY")
        target_key = config_manager.get("TARGET_API_KEY")
        
        if (proxy_key and token == proxy_key) or (target_key and token == target_key):
            return -1  # Special ID for config-based auth
        
        # Then check database for registered API keys
        key_hash = hash_api_key(token)
        api_key_obj = db.query(ApiKey).filter(
            ApiKey.key_hash == key_hash,
            ApiKey.status == "active"
        ).first()
        
        if not api_key_obj:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key"
            )
        
        # Check expiry
        if api_key_obj.expire_at and api_key_obj.expire_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key expired"
            )
        
        return api_key_obj.id
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API key verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    api_key_id: int = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """OpenAI Chat Completions API"""
    start_time = time.time()
    
    # Rate limiting
    client_ip = raw_request.client.host
    await check_rate_limit(api_key_id, client_ip)
    
    logging_service = get_logging_service(db)
    
    # Get API key name for metrics
    api_key_name = "unknown"
    try:
        api_key_obj = db.query(ApiKey).filter(ApiKey.id == api_key_id).first()
        if api_key_obj:
            api_key_name = api_key_obj.name
    except:
        pass
    
    # Start logging
    headers = dict(raw_request.headers)
    log_id = logging_service.start_log(
        route="/v1/chat/completions",
        method="POST",
        headers=headers,
        request_body=request.dict(exclude_none=True),
        api_key_id=api_key_id
    )
    
    try:
        # Handle streaming
        if request.stream:
            return StreamingResponse(
                _stream_chat_completions(request, log_id, db),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive"
                }
            )
        
        # Handle non-streaming
        async with get_provider_adapter(db) as adapter:
            provider_response = await adapter.chat_completions(request)
            
            # Return response
            if provider_response.status_code == 200:
                # Parse successful response
                response_data = provider_response.json()
                token_usage = response_data.get("usage", {})
                model = response_data.get("model", request.model)
                
                # Finish logging for successful request
                logging_service.finish_log(
                    log_id=log_id,
                    proxy_status=200,
                    provider_status=provider_response.status_code,
                    response_body=json.dumps(response_data),
                    token_usage=token_usage,
                    model=model,
                    streamed=False
                )
                
                # Record metrics
                duration = time.time() - start_time
                metrics_collector.record_request("POST", "/v1/chat/completions", 200, duration, api_key_name)
                
                if token_usage:
                    metrics_collector.record_token_usage("prompt", model, token_usage.get("prompt_tokens", 0))
                    metrics_collector.record_token_usage("completion", model, token_usage.get("completion_tokens", 0))
                
                return response_data
            else:
                # Handle provider error - log as error
                error_message = "Provider error"
                error_data = None
                try:
                    error_data = provider_response.json()
                    if isinstance(error_data, dict) and "error" in error_data:
                        error_message = error_data["error"].get("message", "Provider error")
                except json.JSONDecodeError:
                    error_data = {"error": {"message": "Provider error", "type": "provider_error"}}
                
                # Log as error
                logging_service.log_error(
                    log_id=log_id,
                    error_code="provider_error",
                    error_message=error_message,
                    proxy_status=provider_response.status_code,
                    provider_status=provider_response.status_code
                )
                
                # Record error metrics
                duration = time.time() - start_time
                metrics_collector.record_request("POST", "/v1/chat/completions", provider_response.status_code, duration, api_key_name)
                
                raise HTTPException(
                    status_code=provider_response.status_code,
                    detail=error_data
                )
    
    except ProviderError as e:
        logging_service.log_error(
            log_id=log_id,
            error_code="provider_error",
            error_message=str(e),
            proxy_status=e.status_code
        )
        raise HTTPException(status_code=e.status_code, detail={
            "error": {"message": e.message, "type": e.error_type}
        })
    
    except Exception as e:
        logger.error(f"Unexpected error in chat_completions: {e}")
        logging_service.log_error(
            log_id=log_id,
            error_code="internal_error",
            error_message=str(e),
            proxy_status=500
        )
        raise HTTPException(status_code=500, detail={
            "error": {"message": "Internal server error", "type": "internal_error"}
        })

async def _stream_chat_completions(request: ChatCompletionRequest, log_id: int, db: Session):
    """Handle streaming chat completions"""
    logging_service = get_logging_service(db)
    
    try:
        response_chunks = []
        model = request.model
        
        async with get_provider_adapter(db) as adapter:
            async for chunk in adapter.chat_completions_stream(request):
                # Log chunk for aggregation
                logging_service.add_stream_chunk(log_id, chunk)
                response_chunks.append(chunk)
                
                # Extract model from first chunk if possible
                if chunk.startswith('data: ') and not model:
                    try:
                        data_part = chunk[6:].strip()
                        if data_part and data_part != '[DONE]':
                            chunk_data = json.loads(data_part)
                            model = chunk_data.get('model', model)
                    except:
                        pass
                
                yield chunk + "\n"
        
        # Finish logging
        logging_service.finish_log(
            log_id=log_id,
            proxy_status=200,
            provider_status=200,
            model=model,
            streamed=True
        )
    
    except ProviderError as e:
        logging_service.log_error(
            log_id=log_id,
            error_code="provider_error",
            error_message=str(e),
            proxy_status=e.status_code
        )
        yield f"data: {json.dumps({'error': {'message': e.message, 'type': e.error_type}})}\n\n"
    
    except Exception as e:
        logger.error(f"Unexpected error in streaming chat_completions: {e}")
        logging_service.log_error(
            log_id=log_id,
            error_code="internal_error",
            error_message=str(e),
            proxy_status=500
        )
        yield f"data: {json.dumps({'error': {'message': 'Internal server error', 'type': 'internal_error'}})}\n\n"

@router.post("/responses")
async def responses(
    request: ResponsesRequest,
    raw_request: Request,
    api_key_id: int = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """OpenAI Responses API"""
    logging_service = get_logging_service(db)
    
    # Start logging
    headers = dict(raw_request.headers)
    log_id = logging_service.start_log(
        route="/v1/responses",
        method="POST",
        headers=headers,
        request_body=request.dict(exclude_none=True),
        api_key_id=api_key_id
    )
    
    try:
        # Check if streaming (responses API may use different parameter)
        request_dict = request.dict(exclude_none=True)
        is_streaming = request_dict.get("stream", False)
        
        if is_streaming:
            return StreamingResponse(
                _stream_responses(request, log_id, db),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive"
                }
            )
        
        # Handle non-streaming
        async with get_provider_adapter(db) as adapter:
            provider_response = await adapter.responses(request)
            
            # Return response
            if provider_response.status_code == 200:
                # Parse successful response
                response_data = provider_response.json()
                token_usage = response_data.get("usage", {})
                model = response_data.get("model")
                
                # Finish logging for successful request
                logging_service.finish_log(
                    log_id=log_id,
                    proxy_status=200,
                    provider_status=provider_response.status_code,
                    response_body=json.dumps(response_data),
                    token_usage=token_usage,
                    model=model,
                    streamed=False
                )
                
                return response_data
            else:
                # Handle provider error - log as error
                error_message = "Provider error"
                error_data = None
                try:
                    error_data = provider_response.json()
                    if isinstance(error_data, dict) and "error" in error_data:
                        error_message = error_data["error"].get("message", "Provider error")
                except json.JSONDecodeError:
                    error_data = {"error": {"message": "Provider error", "type": "provider_error"}}
                
                # Log as error
                logging_service.log_error(
                    log_id=log_id,
                    error_code="provider_error",
                    error_message=error_message,
                    proxy_status=provider_response.status_code,
                    provider_status=provider_response.status_code
                )
                
                raise HTTPException(
                    status_code=provider_response.status_code,
                    detail=error_data
                )
    
    except ProviderError as e:
        logging_service.log_error(
            log_id=log_id,
            error_code="provider_error",
            error_message=str(e),
            proxy_status=e.status_code
        )
        raise HTTPException(status_code=e.status_code, detail={
            "error": {"message": e.message, "type": e.error_type}
        })
    
    except Exception as e:
        logger.error(f"Unexpected error in responses: {e}")
        logging_service.log_error(
            log_id=log_id,
            error_code="internal_error",
            error_message=str(e),
            proxy_status=500
        )
        raise HTTPException(status_code=500, detail={
            "error": {"message": "Internal server error", "type": "internal_error"}
        })

async def _stream_responses(request: ResponsesRequest, log_id: int, db: Session):
    """Handle streaming responses"""
    logging_service = get_logging_service(db)
    
    try:
        response_chunks = []
        model = None
        
        async with get_provider_adapter(db) as adapter:
            async for chunk in adapter.responses_stream(request):
                # Log chunk for aggregation
                logging_service.add_stream_chunk(log_id, chunk)
                response_chunks.append(chunk)
                
                # Extract model from first chunk if possible
                if chunk.startswith('data: ') and not model:
                    try:
                        data_part = chunk[6:].strip()
                        if data_part and data_part != '[DONE]':
                            chunk_data = json.loads(data_part)
                            model = chunk_data.get('model', model)
                    except:
                        pass
                
                yield chunk + "\n"
        
        # Finish logging
        logging_service.finish_log(
            log_id=log_id,
            proxy_status=200,
            provider_status=200,
            model=model,
            streamed=True
        )
    
    except ProviderError as e:
        logging_service.log_error(
            log_id=log_id,
            error_code="provider_error",
            error_message=str(e),
            proxy_status=e.status_code
        )
        yield f"data: {json.dumps({'error': {'message': e.message, 'type': e.error_type}})}\n\n"
    
    except Exception as e:
        logger.error(f"Unexpected error in streaming responses: {e}")
        logging_service.log_error(
            log_id=log_id,
            error_code="internal_error",
            error_message=str(e),
            proxy_status=500
        )
        yield f"data: {json.dumps({'error': {'message': 'Internal server error', 'type': 'internal_error'}})}\n\n"

@router.get("/models")
async def models(
    api_key_id: int = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """OpenAI Models API"""
    logging_service = get_logging_service(db)
    
    # Start logging
    log_id = logging_service.start_log(
        route="/v1/models",
        method="GET",
        headers={},
        api_key_id=api_key_id
    )
    
    try:
        async with get_provider_adapter(db) as adapter:
            provider_response = await adapter.models()
            
            # Return response
            if provider_response.status_code == 200:
                # Parse successful response
                response_data = provider_response.json()
                
                # Finish logging for successful request
                logging_service.finish_log(
                    log_id=log_id,
                    proxy_status=200,
                    provider_status=provider_response.status_code,
                    response_body=json.dumps(response_data),
                    streamed=False
                )
                
                return response_data
            else:
                # Handle provider error - log as error
                error_message = "Provider error"
                error_data = None
                try:
                    error_data = provider_response.json()
                    if isinstance(error_data, dict) and "error" in error_data:
                        error_message = error_data["error"].get("message", "Provider error")
                except json.JSONDecodeError:
                    error_data = {"error": {"message": "Provider error", "type": "provider_error"}}
                
                # Log as error
                logging_service.log_error(
                    log_id=log_id,
                    error_code="provider_error",
                    error_message=error_message,
                    proxy_status=provider_response.status_code,
                    provider_status=provider_response.status_code
                )
                
                raise HTTPException(
                    status_code=provider_response.status_code,
                    detail=error_data
                )
    
    except ProviderError as e:
        logging_service.log_error(
            log_id=log_id,
            error_code="provider_error",
            error_message=str(e),
            proxy_status=e.status_code
        )
        raise HTTPException(status_code=e.status_code, detail={
            "error": {"message": e.message, "type": e.error_type}
        })
    
    except Exception as e:
        logger.error(f"Unexpected error in models: {e}")
        logging_service.log_error(
            log_id=log_id,
            error_code="internal_error",
            error_message=str(e),
            proxy_status=500
        )
        raise HTTPException(status_code=500, detail={
            "error": {"message": "Internal server error", "type": "internal_error"}
        })