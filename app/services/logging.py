import json
import re
import hashlib
import time
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from app.models.models import Log, LogChunk, ApiKey
from app.core.config import get_config_manager
import logging

logger = logging.getLogger(__name__)

class StreamCollector:
    """Collects streaming chunks for later aggregation"""
    def __init__(self, log_id: int, max_buffer_size: int = 1048576):  # 1MB default
        self.log_id = log_id
        self.chunks = []
        self.content_parts = []
        self.current_size = 0
        self.max_buffer_size = max_buffer_size
        self.truncated = False
    
    def add_chunk(self, chunk_text: str) -> None:
        """Add a chunk and extract content for aggregation"""
        if self.current_size >= self.max_buffer_size:
            if not self.truncated:
                logger.warning(f"Stream buffer limit reached for log {self.log_id}")
                self.truncated = True
            return
        
        self.chunks.append({
            'seq': len(self.chunks),
            'chunk_text': chunk_text,
            'created_at': datetime.now(timezone.utc)
        })
        
        # Try to extract content from chunk
        try:
            if chunk_text.startswith('data: '):
                data_part = chunk_text[6:].strip()
                if data_part and data_part != '[DONE]':
                    chunk_data = json.loads(data_part)
                    # Extract content from delta (OpenAI format)
                    if 'choices' in chunk_data:
                        for choice in chunk_data['choices']:
                            if 'delta' in choice and 'content' in choice['delta']:
                                content = choice['delta']['content']
                                if content:
                                    self.content_parts.append(content)
                                    self.current_size += len(content)
        except (json.JSONDecodeError, KeyError) as e:
            # Skip invalid chunks
            pass
    
    def get_aggregated_content(self) -> str:
        """Get the full aggregated content"""
        return ''.join(self.content_parts)
    
    def get_chunks(self) -> List[Dict[str, Any]]:
        """Get all chunks"""
        return self.chunks

class LoggingService:
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.config_manager = get_config_manager(db_session)
        self.stream_collectors: Dict[int, StreamCollector] = {}
    
    def _redact_content(self, content: str) -> str:
        """Apply redaction rules to content"""
        if not self.config_manager.get("REDACT_LOGS", False):
            return content
        
        # Basic redaction rules
        redacted = content
        
        # Email addresses
        redacted = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 
                         lambda m: m.group(0)[:3] + '***@***' + m.group(0)[-4:], 
                         redacted)
        
        # Phone numbers (simple pattern)
        redacted = re.sub(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', '***-***-****', redacted)
        
        # Credit card numbers (simple pattern)
        redacted = re.sub(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '****-****-****-****', redacted)
        
        return redacted
    
    def _truncate_content(self, content: str, max_length: int = 65536) -> tuple[str, bool]:
        """Truncate content if too long"""
        if len(content) <= max_length:
            return content, False
        
        # Keep first and last parts
        half = max_length // 2 - 50
        truncated = content[:half] + "\n... [TRUNCATED] ...\n" + content[-half:]
        return truncated, True
    
    def _hash_headers(self, headers: Dict[str, str]) -> str:
        """Create hash of headers for auditing"""
        # Remove sensitive headers
        safe_headers = {k: v for k, v in headers.items() 
                       if k.lower() not in ['authorization', 'cookie', 'x-api-key']}
        header_str = json.dumps(safe_headers, sort_keys=True)
        return hashlib.md5(header_str.encode()).hexdigest()
    
    def start_log(
        self, 
        route: str, 
        method: str, 
        headers: Dict[str, str],
        request_body: Optional[Dict[str, Any]] = None,
        api_key_id: Optional[int] = None
    ) -> int:
        """Start logging a request"""
        
        # Create preview and full copy of request body
        request_preview = None
        request_full = None
        if request_body:
            try:
                request_str = json.dumps(request_body, ensure_ascii=False, indent=2)
                request_str = self._redact_content(request_str)
                request_preview, _ = self._truncate_content(request_str, 1024)  # Shorter preview
                request_full = request_str  # Store full content
            except Exception as e:
                logger.error(f"Error creating request preview: {e}")
                request_preview = f"Error serializing request: {str(e)}"
                request_full = request_preview
        
        # Get provider config for URL
        provider_config = self.config_manager.get_provider_config()
        
        log_entry = Log(
            created_at=datetime.now(timezone.utc),
            route=route,
            method=method.upper(),
            client_api_key_id=api_key_id,
            provider_base_url=provider_config["target_base_url"],
            request_headers_hash=self._hash_headers(headers),
            request_body_preview=request_preview,
            request_body_full=request_full
        )
        
        self.db_session.add(log_entry)
        self.db_session.commit()
        self.db_session.refresh(log_entry)
        
        return log_entry.id
    
    def finish_log(
        self, 
        log_id: int, 
        proxy_status: int,
        provider_status: Optional[int] = None,
        response_body: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        token_usage: Optional[Dict[str, int]] = None,
        model: Optional[str] = None,
        streamed: bool = False
    ) -> None:
        """Finish logging a request"""
        
        log_entry = self.db_session.query(Log).filter(Log.id == log_id).first()
        if not log_entry:
            logger.error(f"Log entry {log_id} not found")
            return
        
        # Calculate latency
        finished_at = datetime.now(timezone.utc)
        
        # Handle potential offset-naive datetime from database
        created_at = log_entry.created_at
        if created_at.tzinfo is None:
            # Assume naive datetime is UTC
            created_at = created_at.replace(tzinfo=timezone.utc)
        
        latency_ms = int((finished_at - created_at).total_seconds() * 1000)
        
        # Handle streaming response aggregation
        if streamed and log_id in self.stream_collectors:
            collector = self.stream_collectors[log_id]
            aggregated_content = collector.get_aggregated_content()
            
            # Save chunks if needed
            for chunk_data in collector.get_chunks():
                chunk = LogChunk(
                    log_id=log_id,
                    seq=chunk_data['seq'],
                    chunk_text=chunk_data['chunk_text'],
                    created_at=chunk_data['created_at']
                )
                self.db_session.add(chunk)
            
            # Use aggregated content as response body
            if aggregated_content and not response_body:
                response_body = aggregated_content
            
            # Mark as truncated if collector hit buffer limit
            if collector.truncated:
                log_entry.truncated = True
            
            # Clean up collector
            del self.stream_collectors[log_id]
        
        # Process response body
        response_preview = None
        response_full = None
        if response_body:
            try:
                # Try to parse and format as JSON if possible
                if isinstance(response_body, str):
                    try:
                        parsed = json.loads(response_body)
                        response_str = json.dumps(parsed, ensure_ascii=False, indent=2)
                    except json.JSONDecodeError:
                        response_str = response_body
                else:
                    response_str = json.dumps(response_body, ensure_ascii=False, indent=2)
                
                response_str = self._redact_content(response_str)
                response_preview, truncated_preview = self._truncate_content(response_str, 1024)  # Shorter preview
                response_full = response_str  # Store full content
                
                if truncated_preview:
                    log_entry.truncated = True
                    
            except Exception as e:
                logger.error(f"Error processing response body: {e}")
                response_preview = f"Error processing response: {str(e)}"
                response_full = str(response_body)
        
        # Update log entry
        log_entry.finished_at = finished_at
        log_entry.latency_ms = latency_ms
        log_entry.proxy_status = proxy_status
        log_entry.provider_status = provider_status
        log_entry.response_body_preview = response_preview
        log_entry.response_body_full = response_full
        log_entry.streamed = streamed
        log_entry.error_code = error_code
        log_entry.error_message = error_message
        log_entry.provider_model = model
        
        if token_usage:
            log_entry.token_usage_prompt = token_usage.get('prompt_tokens')
            log_entry.token_usage_completion = token_usage.get('completion_tokens') 
            log_entry.token_usage_total = token_usage.get('total_tokens')
        
        self.db_session.commit()
    
    def add_stream_chunk(self, log_id: int, chunk_text: str) -> None:
        """Add a streaming chunk"""
        if log_id not in self.stream_collectors:
            config = self.config_manager
            buffer_limit = int(config.get("STREAM_BUFFER_LIMIT", 1048576))
            self.stream_collectors[log_id] = StreamCollector(log_id, buffer_limit)
        
        self.stream_collectors[log_id].add_chunk(chunk_text)
    
    def log_error(
        self, 
        log_id: int, 
        error_code: str, 
        error_message: str, 
        proxy_status: int = 500,
        provider_status: Optional[int] = None
    ) -> None:
        """Log an error for a request"""
        self.finish_log(
            log_id=log_id,
            proxy_status=proxy_status,
            provider_status=provider_status,
            error_code=error_code,
            error_message=error_message
        )
    
    async def get_api_key_id(self, api_key: str) -> Optional[int]:
        """Get API key ID from database"""
        try:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            api_key_obj = self.db_session.query(ApiKey).filter(
                ApiKey.key_hash == key_hash,
                ApiKey.status == "active"
            ).first()
            
            if api_key_obj:
                # Check expiry
                if api_key_obj.expire_at and api_key_obj.expire_at < datetime.now(timezone.utc):
                    return None
                return api_key_obj.id
            
            return None
        except Exception as e:
            logger.error(f"Error looking up API key: {e}")
            return None

def get_logging_service(db_session: Session) -> LoggingService:
    """Get logging service instance"""
    return LoggingService(db_session)