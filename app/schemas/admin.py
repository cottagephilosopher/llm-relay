from pydantic import BaseModel, field_serializer
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

# Connection test schema
class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    model_count: Optional[int] = None

# Settings schemas
class SettingsUpdate(BaseModel):
    proxy_base_url: Optional[str] = None
    target_base_url: Optional[str] = None
    target_api_key: Optional[str] = None
    default_model: Optional[str] = None
    redact_logs: Optional[bool] = None
    http_timeout_seconds: Optional[int] = None
    http_max_retries: Optional[int] = None

class SettingsResponse(BaseModel):
    id: int
    proxy_base_url: str
    proxy_key: str
    target_base_url: str
    target_api_key: str
    default_model: str
    redact_logs: bool
    http_timeout_seconds: int
    http_max_retries: int
    created_at: datetime
    updated_at: datetime
    
    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime, _info):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    
    class Config:
        from_attributes = True

# API Key schemas
class ApiKeyCreate(BaseModel):
    name: str
    expire_at: Optional[datetime] = None

class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    expire_at: Optional[datetime] = None

class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    status: str
    expire_at: Optional[datetime]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    full_key: Optional[str] = None  # Only returned when creating new key
    
    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, dt: datetime, _info):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    
    @field_serializer('expire_at')
    def serialize_expire_at(self, dt: Optional[datetime], _info):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    
    class Config:
        from_attributes = True

# Log schemas
class LogFilter(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    route: Optional[str] = None
    method: Optional[str] = None
    status: Optional[str] = None  # success/error
    model: Optional[str] = None
    api_key_id: Optional[int] = None
    streamed: Optional[bool] = None
    search: Optional[str] = None
    page: int = 1
    page_size: int = 50

class LogResponse(BaseModel):
    id: int
    created_at: datetime
    finished_at: Optional[datetime]
    latency_ms: Optional[int]
    route: str
    method: str
    provider_model: Optional[str]
    streamed: bool
    proxy_status: Optional[int]
    provider_status: Optional[int]
    error_code: Optional[str]
    error_message: Optional[str]
    token_usage_total: Optional[int]
    api_key_name: Optional[str] = None
    
    @field_serializer('created_at')
    def serialize_created_at(self, dt: datetime, _info):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    
    @field_serializer('finished_at')
    def serialize_finished_at(self, dt: Optional[datetime], _info):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    
    class Config:
        from_attributes = True

class LogDetailResponse(BaseModel):
    id: int
    created_at: datetime
    finished_at: Optional[datetime]
    latency_ms: Optional[int]
    route: str
    method: str
    client_api_key_id: Optional[int]
    provider_base_url: str
    provider_model: Optional[str]
    request_body_preview: Optional[str]
    request_body_full: Optional[str]
    response_body_preview: Optional[str]
    response_body_full: Optional[str]
    streamed: bool
    proxy_status: Optional[int]
    provider_status: Optional[int]
    error_code: Optional[str]
    error_message: Optional[str]
    token_usage_prompt: Optional[int]
    token_usage_completion: Optional[int]
    token_usage_total: Optional[int]
    cost_estimated: Optional[float]
    truncated: bool
    partial: bool
    
    @field_serializer('created_at')
    def serialize_created_at(self, dt: datetime, _info):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    
    @field_serializer('finished_at')
    def serialize_finished_at(self, dt: Optional[datetime], _info):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    
    class Config:
        from_attributes = True

class LogListResponse(BaseModel):
    logs: List[LogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

# Dashboard stats
class DashboardStats(BaseModel):
    today_requests: int
    today_success_rate: float
    p95_latency: Optional[float]
    model_usage: Dict[str, int]
    stream_percentage: float
    error_rate_24h: float

# Authentication
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"