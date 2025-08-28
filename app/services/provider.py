import httpx
import asyncio
import json
import time
import logging
from typing import Dict, Any, Optional, AsyncIterator
from contextlib import asynccontextmanager
from app.core.config import get_config_manager
from app.schemas.openai import ChatCompletionRequest, ResponsesRequest

logger = logging.getLogger(__name__)

class ProviderError(Exception):
    def __init__(self, status_code: int, message: str, error_type: str = "provider_error"):
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        super().__init__(message)

class ProviderAdapter:
    def __init__(self, db_session=None):
        self.config_manager = get_config_manager(db_session)
        self.client = None
    
    async def __aenter__(self):
        provider_config = self.config_manager.get_provider_config()
        timeout = httpx.Timeout(
            timeout=provider_config["http_timeout_seconds"],
            connect=10.0,
            read=provider_config["http_timeout_seconds"]
        )
        
        self.client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            verify=False  # Skip SSL verification for compatibility
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    def _prepare_headers(self) -> Dict[str, str]:
        provider_config = self.config_manager.get_provider_config()
        return {
            "Authorization": f"Bearer {provider_config['target_api_key']}",
            "Content-Type": "application/json",
            "User-Agent": "LLM-Relay/1.0"
        }
    
    def _prepare_request_data(self, request_data: Dict[str, Any], endpoint: str) -> Dict[str, Any]:
        """Prepare request data, adding default model if needed"""
        data = request_data.copy()
        
        # Add default model if not specified
        if endpoint in ["/v1/chat/completions", "/v1/responses"] and not data.get("model"):
            provider_config = self.config_manager.get_provider_config()
            data["model"] = provider_config["default_model"]
        
        return data
    
    def _build_url(self, endpoint: str) -> str:
        provider_config = self.config_manager.get_provider_config()
        base_url = provider_config["target_base_url"].rstrip("/")
        return f"{base_url}{endpoint}"
    
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict[str, Any]] = None
    ) -> httpx.Response:
        """Make HTTP request to provider with retry logic"""
        provider_config = self.config_manager.get_provider_config()
        max_retries = provider_config["http_max_retries"]
        
        url = self._build_url(endpoint)
        headers = self._prepare_headers()
        
        if data:
            data = self._prepare_request_data(data, endpoint)
        
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                if method.upper() == "GET":
                    response = await self.client.get(url, headers=headers)
                elif method.upper() == "POST":
                    response = await self.client.post(url, headers=headers, json=data)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                # Don't retry on client errors (4xx)
                if 400 <= response.status_code < 500:
                    return response
                
                # Return successful responses
                if response.status_code < 400:
                    return response
                
                # Retry on server errors (5xx) and rate limits (429)
                if response.status_code >= 500 or response.status_code == 429:
                    if attempt < max_retries:
                        # Exponential backoff
                        wait_time = (2 ** attempt) * 1.0
                        logger.warning(
                            f"Request failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"status: {response.status_code}, waiting {wait_time}s"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                
                return response
                
            except (httpx.RequestError, httpx.TimeoutException) as e:
                last_exception = e
                if attempt < max_retries:
                    wait_time = (2 ** attempt) * 1.0
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{max_retries + 1}), "
                        f"error: {e}, waiting {wait_time}s"
                    )
                    await asyncio.sleep(wait_time)
                    continue
        
        # All retries exhausted
        if last_exception:
            logger.error(f"Request failed after {max_retries + 1} attempts: {last_exception}")
            raise ProviderError(502, f"Provider request failed: {str(last_exception)}")
        
        # This shouldn't happen, but just in case
        raise ProviderError(502, "Unknown provider error")
    
    async def chat_completions(
        self, 
        request: ChatCompletionRequest
    ) -> httpx.Response:
        """Forward chat completions request to provider"""
        return await self._make_request("POST", "/v1/chat/completions", request.dict(exclude_none=True))
    
    async def chat_completions_stream(
        self, 
        request: ChatCompletionRequest
    ) -> AsyncIterator[str]:
        """Forward streaming chat completions request to provider"""
        request_data = request.dict(exclude_none=True)
        request_data["stream"] = True
        
        url = self._build_url("/v1/chat/completions")
        headers = self._prepare_headers()
        request_data = self._prepare_request_data(request_data, "/v1/chat/completions")
        
        try:
            async with self.client.stream(
                "POST", 
                url, 
                headers=headers, 
                json=request_data
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise ProviderError(
                        response.status_code, 
                        f"Provider streaming error: {error_text.decode()}"
                    )
                
                async for chunk in response.aiter_lines():
                    if chunk.strip():
                        yield chunk
        
        except httpx.RequestError as e:
            raise ProviderError(502, f"Provider streaming request failed: {str(e)}")
    
    async def responses(self, request: ResponsesRequest) -> httpx.Response:
        """Forward responses request to provider"""
        return await self._make_request("POST", "/v1/responses", request.dict(exclude_none=True))
    
    async def responses_stream(self, request: ResponsesRequest) -> AsyncIterator[str]:
        """Forward streaming responses request to provider"""
        request_data = request.dict(exclude_none=True)
        # Responses API uses different streaming parameter
        request_data["stream"] = True
        
        url = self._build_url("/v1/responses")
        headers = self._prepare_headers()
        request_data = self._prepare_request_data(request_data, "/v1/responses")
        
        try:
            async with self.client.stream(
                "POST", 
                url, 
                headers=headers, 
                json=request_data
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise ProviderError(
                        response.status_code, 
                        f"Provider streaming error: {error_text.decode()}"
                    )
                
                async for chunk in response.aiter_lines():
                    if chunk.strip():
                        yield chunk
        
        except httpx.RequestError as e:
            raise ProviderError(502, f"Provider streaming request failed: {str(e)}")
    
    async def models(self) -> httpx.Response:
        """Get models list from provider"""
        return await self._make_request("GET", "/v1/models")

@asynccontextmanager
async def get_provider_adapter(db_session=None):
    """Context manager for ProviderAdapter"""
    async with ProviderAdapter(db_session) as adapter:
        yield adapter