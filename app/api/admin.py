from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, and_

from app.db.base import get_db
from app.schemas.admin import (
    SettingsUpdate, 
    SettingsResponse,
    ApiKeyCreate,
    ApiKeyUpdate, 
    ApiKeyResponse,
    LogFilter,
    LogResponse,
    LogDetailResponse,
    LogListResponse,
    DashboardStats,
    LoginRequest,
    TokenResponse,
    ConnectionTestResponse
)
from app.models.models import Settings, ApiKey, Log
from app.core.security import (
    authenticate_admin,
    create_access_token,
    verify_token,
    generate_api_key,
    hash_api_key,
    extract_key_prefix
)
from app.core.config import settings
import httpx
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin API"])
security = HTTPBasic()
bearer_security = HTTPBearer()

def verify_admin_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials"""
    if not authenticate_admin(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

def verify_admin_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_security)):
    """Verify admin token"""
    try:
        token = credentials.credentials
        username = verify_token(token)  # verify_token already returns username
        return username
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

@router.post("/login", response_model=TokenResponse)
async def login(login_data: LoginRequest):
    """Admin login endpoint"""
    if not authenticate_admin(login_data.username, login_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    access_token = create_access_token(data={"sub": login_data.username})
    return TokenResponse(access_token=access_token)

@router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Get dashboard statistics"""
    
    # Today's requests
    today = datetime.now(timezone.utc).date()
    today_requests = db.query(Log).filter(
        func.date(Log.created_at) == today
    ).count()
    
    # Success rate (today)
    today_success = db.query(Log).filter(
        and_(
            func.date(Log.created_at) == today,
            Log.proxy_status < 400
        )
    ).count()
    
    success_rate = (today_success / today_requests * 100) if today_requests > 0 else 100.0
    
    # P95 latency (last 24 hours)
    yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
    latencies = db.query(Log.latency_ms).filter(
        and_(
            Log.created_at >= yesterday,
            Log.latency_ms.isnot(None)
        )
    ).all()
    
    p95_latency = None
    if latencies:
        sorted_latencies = sorted([l[0] for l in latencies])
        p95_index = int(0.95 * len(sorted_latencies))
        p95_latency = sorted_latencies[p95_index] if p95_index < len(sorted_latencies) else None
    
    # Model usage (last 7 days)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    model_stats = db.query(
        Log.provider_model,
        func.count().label('count')
    ).filter(
        Log.created_at >= week_ago
    ).group_by(Log.provider_model).all()
    
    model_usage = {stat[0] or 'unknown': stat[1] for stat in model_stats}
    
    # Stream percentage (last 24 hours)
    total_last_24h = db.query(Log).filter(Log.created_at >= yesterday).count()
    streamed_last_24h = db.query(Log).filter(
        and_(
            Log.created_at >= yesterday,
            Log.streamed == True
        )
    ).count()
    
    stream_percentage = (streamed_last_24h / total_last_24h * 100) if total_last_24h > 0 else 0.0
    
    # Error rate (last 24 hours)
    error_last_24h = db.query(Log).filter(
        and_(
            Log.created_at >= yesterday,
            Log.proxy_status >= 400
        )
    ).count()
    
    error_rate_24h = (error_last_24h / total_last_24h * 100) if total_last_24h > 0 else 0.0
    
    return DashboardStats(
        today_requests=today_requests,
        today_success_rate=success_rate,
        p95_latency=p95_latency,
        model_usage=model_usage,
        stream_percentage=stream_percentage,
        error_rate_24h=error_rate_24h
    )

@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Get current settings"""
    settings_obj = db.query(Settings).first()
    
    if not settings_obj:
        # Create default settings
        from app.core.config import settings as config_settings
        settings_obj = Settings(
            proxy_base_url=config_settings.proxy_base_url,
            proxy_key=config_settings.proxy_key,
            target_base_url=config_settings.target_base_url,
            target_api_key=config_settings.target_api_key or "",
            default_model=config_settings.default_model,
            redact_logs=config_settings.redact_logs,
            http_timeout_seconds=config_settings.http_timeout_seconds,
            http_max_retries=config_settings.http_max_retries
        )
        db.add(settings_obj)
        db.commit()
        db.refresh(settings_obj)
    
    return settings_obj

@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    settings_update: SettingsUpdate,
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Update settings"""
    settings_obj = db.query(Settings).first()
    
    if not settings_obj:
        # Create new settings
        settings_obj = Settings()
        db.add(settings_obj)
    
    # Update fields
    update_data = settings_update.dict(exclude_none=True)
    for field, value in update_data.items():
        setattr(settings_obj, field, value)
    
    settings_obj.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(settings_obj)
    
    return settings_obj

@router.get("/api-keys", response_model=List[ApiKeyResponse])
async def get_api_keys(
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Get all API keys"""
    api_keys = db.query(ApiKey).order_by(desc(ApiKey.created_at)).all()
    return api_keys

@router.post("/api-keys", response_model=ApiKeyResponse)
async def create_api_key(
    api_key_data: ApiKeyCreate,
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Create new API key"""
    
    # Generate new API key
    new_key = generate_api_key()
    key_hash = hash_api_key(new_key)
    key_prefix = extract_key_prefix(new_key)
    
    api_key_obj = ApiKey(
        name=api_key_data.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        status="active",
        expire_at=api_key_data.expire_at,
        created_by=admin_user
    )
    
    db.add(api_key_obj)
    db.commit()
    db.refresh(api_key_obj)
    
    # Return the new key in the response (one time only)
    response = ApiKeyResponse.from_orm(api_key_obj)
    # Add the full key for initial display
    response.full_key = new_key
    
    return response

@router.put("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: int,
    api_key_update: ApiKeyUpdate,
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Update API key"""
    
    api_key_obj = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not api_key_obj:
        raise HTTPException(status_code=404, detail="API key not found")
    
    # Update fields
    update_data = api_key_update.dict(exclude_none=True)
    for field, value in update_data.items():
        setattr(api_key_obj, field, value)
    
    api_key_obj.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(api_key_obj)
    
    return api_key_obj

@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: int,
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Delete API key"""
    
    api_key_obj = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not api_key_obj:
        raise HTTPException(status_code=404, detail="API key not found")
    
    db.delete(api_key_obj)
    db.commit()
    
    return Response(content='{"message": "API key deleted successfully"}', media_type="application/json")

@router.get("/logs", response_model=LogListResponse)
async def get_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    route: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    status: Optional[str] = Query(None),  # success/error
    model: Optional[str] = Query(None),
    api_key_id: Optional[int] = Query(None),
    streamed: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Get logs with filtering and pagination"""
    
    query = db.query(Log)
    
    # Apply filters
    if start_date:
        query = query.filter(Log.created_at >= start_date)
    if end_date:
        query = query.filter(Log.created_at <= end_date)
    if route:
        query = query.filter(Log.route == route)
    if method:
        query = query.filter(Log.method == method.upper())
    if status:
        if status == "success":
            query = query.filter(Log.proxy_status < 400)
        elif status == "error":
            query = query.filter(Log.proxy_status >= 400)
    if model:
        query = query.filter(Log.provider_model == model)
    if api_key_id:
        query = query.filter(Log.client_api_key_id == api_key_id)
    if streamed is not None:
        query = query.filter(Log.streamed == streamed)
    if search:
        query = query.filter(
            Log.request_body_preview.contains(search) |
            Log.response_body_preview.contains(search) |
            Log.error_message.contains(search)
        )
    
    # Count total
    total = query.count()
    
    # Apply pagination and ordering
    offset = (page - 1) * page_size
    logs = query.order_by(desc(Log.created_at)).offset(offset).limit(page_size).all()
    
    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size
    
    return LogListResponse(
        logs=logs,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )

@router.get("/logs/{log_id}", response_model=LogDetailResponse)
async def get_log_detail(
    log_id: int,
    admin_user: str = Depends(verify_admin_token),
    db: Session = Depends(get_db)
):
    """Get detailed log information"""
    
    log = db.query(Log).filter(Log.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    
    return log

@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_connection(
    connection_data: dict,
    admin_user: str = Depends(verify_admin_token)
):
    """Test connection to target provider"""
    
    target_base_url = connection_data.get("target_base_url")
    target_api_key = connection_data.get("target_api_key")
    
    if not target_base_url or not target_api_key:
        return ConnectionTestResponse(success=False, message="缺少必要的连接参数")
    
    try:
        # 构建测试请求 - 使用与provider.py相同的请求头
        headers = {
            "Authorization": f"Bearer {target_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "LLM-Relay/1.0"
        }
        
        # 使用chat/completions端点进行测试，应用和provider.py相同的URL构建逻辑
        base_url = target_base_url.rstrip('/')
        if "chat/completions" in base_url:
            test_url = base_url  # 如果已包含chat/completions路径，直接使用
        else:
            test_url = f"{base_url}/v1/chat/completions"
        
        # 构建测试请求体 - 使用配置中的默认模型
        default_model = connection_data.get("default_model", "doubao-1-5-pro-256k-250115")
        test_payload = {
            "model": default_model,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 1
        }
        
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            response = await client.post(test_url, headers=headers, json=test_payload)
            
            if response.status_code == 200:
                return ConnectionTestResponse(
                    success=True, 
                    message="连接成功，API响应正常"
                )
            else:
                error_detail = ""
                try:
                    error_data = response.json()
                    if isinstance(error_data, dict) and "error" in error_data:
                        error_detail = f": {error_data['error'].get('message', '')}"
                except:
                    pass
                
                return ConnectionTestResponse(
                    success=False, 
                    message=f"API 返回错误状态码: {response.status_code}{error_detail}"
                )
                
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message="连接超时，请检查网络或目标地址")
    except httpx.RequestError as e:
        return ConnectionTestResponse(success=False, message=f"网络请求失败: {str(e)}")
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return ConnectionTestResponse(success=False, message=f"连接测试失败: {str(e)}")