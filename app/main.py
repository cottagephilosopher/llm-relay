import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
import uvicorn

from app.api import v1, admin
from app.db.base import engine, Base
from app.core.config import settings
from app.models.models import Settings as DBSettings, ApiKey
from app.core.security import hash_api_key, extract_key_prefix

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Create database tables
    Base.metadata.create_all(bind=engine)
    
    # Initialize default data
    from app.db.base import SessionLocal
    db = SessionLocal()
    try:
        # Create default settings if they don't exist
        if not db.query(DBSettings).first():
            default_settings = DBSettings(
                proxy_base_url=settings.proxy_base_url,
                proxy_key=settings.proxy_key,
                target_base_url=settings.target_base_url,
                target_api_key=settings.target_api_key or "",
                default_model=settings.default_model,
                redact_logs=settings.redact_logs,
                http_timeout_seconds=settings.http_timeout_seconds,
                http_max_retries=settings.http_max_retries
            )
            db.add(default_settings)
        
        # Create default API key if none exist
        if not db.query(ApiKey).first():
            default_key_hash = hash_api_key(settings.proxy_key)
            default_key_prefix = extract_key_prefix(settings.proxy_key)
            
            default_api_key = ApiKey(
                name="Default API Key",
                key_hash=default_key_hash,
                key_prefix=default_key_prefix,
                status="active",
                created_by="system"
            )
            db.add(default_api_key)
        
        db.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        db.rollback()
    finally:
        db.close()
    
    logger.info(f"LLM Relay started on {settings.proxy_base_url}")
    yield
    
    logger.info("LLM Relay shutting down")

# Create FastAPI app
app = FastAPI(
    title="LLM Relay",
    description="OpenAI-compatible LLM/VLM proxy with logging and management",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# Include routers
app.include_router(v1.router)
app.include_router(admin.router)

# Monitoring endpoints
from app.services.monitoring import metrics_collector, get_metrics_response

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return get_metrics_response()

@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return metrics_collector.get_health_status()

# Mount static files (will be created for the admin dashboard)
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except RuntimeError:
    # Static directory doesn't exist yet
    pass

# Templates
import os
template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
try:
    if os.path.exists(template_dir):
        templates = Jinja2Templates(directory=template_dir)
    else:
        templates = None
except Exception as e:
    print(f"Template initialization failed: {e}")
    templates = None

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root endpoint - redirect to admin login"""
    return RedirectResponse(url="/admin/login")

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Admin login page"""
    if templates:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "title": "管理员登录"}
        )
    else:
        return HTMLResponse(content="<h1>Login page not available</h1>")

@app.get("/admin/settings-page", response_class=HTMLResponse)
async def admin_settings_page(request: Request):
    """Admin settings page"""
    if templates:
        return templates.TemplateResponse(
            "settings.html",
            {"request": request, "title": "系统设置"}
        )
    else:
        return HTMLResponse(content="<h1>Settings page not available</h1>")

@app.get("/admin/logs-page", response_class=HTMLResponse)
async def admin_logs_page(request: Request):
    """Admin logs page"""
    if templates:
        return templates.TemplateResponse(
            "logs.html",
            {"request": request, "title": "日志查看"}
        )
    else:
        return HTMLResponse(content="<h1>Logs page not available</h1>")

@app.get("/admin/api-keys-page", response_class=HTMLResponse)
async def admin_api_keys_page(request: Request):
    """Admin API keys page"""
    if templates:
        return templates.TemplateResponse(
            "api-keys.html",
            {"request": request, "title": "API 密钥管理"}
        )
    else:
        return HTMLResponse(content="<h1>API Keys management page not available</h1>")

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Admin dashboard page"""
    if templates:
        from app.core.config import settings
        return templates.TemplateResponse(
            "dashboard.html", 
            {
                "request": request, 
                "title": "LLM Relay Dashboard",
                "target_base_url": settings.target_base_url,
                "default_model": settings.default_model
            }
        )
    else:
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html>
        <head>
            <title>LLM Relay Dashboard</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .container { max-width: 800px; margin: 0 auto; }
                .section { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
                .code { background: #f5f5f5; padding: 10px; font-family: monospace; border-radius: 3px; }
                .warning { background: #fff3cd; border: 1px solid #ffeaa7; padding: 10px; border-radius: 5px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>LLM Relay Dashboard</h1>
                
                <div class="warning">
                    <strong>Note:</strong> This is a minimal dashboard. Full web UI templates are not installed.
                </div>
                
                <div class="section">
                    <h2>Configuration</h2>
                    <p><strong>Proxy URL:</strong> <code>""" + settings.proxy_base_url + """</code></p>
                    <p><strong>Target URL:</strong> <code>""" + settings.target_base_url + """</code></p>
                    <p><strong>Default Model:</strong> <code>""" + settings.default_model + """</code></p>
                </div>
                
                <div class="section">
                    <h2>API Usage</h2>
                    <p>Use this proxy as a drop-in replacement for OpenAI API:</p>
                    <div class="code">
curl -X POST """ + settings.proxy_base_url + """/v1/chat/completions \\
  -H "Authorization: Bearer """ + settings.proxy_key + """" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
                    </div>
                </div>
                
                <div class="section">
                    <h2>API Endpoints</h2>
                    <ul>
                        <li><strong>Admin API:</strong> <a href="/docs#/Admin%20API">/admin/*</a></li>
                        <li><strong>OpenAI Chat:</strong> <code>POST /v1/chat/completions</code></li>
                        <li><strong>OpenAI Responses:</strong> <code>POST /v1/responses</code></li>
                        <li><strong>OpenAI Models:</strong> <code>GET /v1/models</code></li>
                        <li><strong>Health Check:</strong> <a href="/healthz">/healthz</a></li>
                        <li><strong>API Docs:</strong> <a href="/docs">/docs</a></li>
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """)


@app.get("/favicon.ico")
async def favicon():
    """Return empty favicon to prevent 404 errors"""
    return Response(content="", media_type="image/x-icon")

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Custom 404 handler"""
    return {"error": "Not found", "path": str(request.url.path)}

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: HTTPException):
    """Custom 500 handler"""
    logger.error(f"Internal server error: {exc}")
    return {"error": "Internal server error"}

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower()
    )