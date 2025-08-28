from pydantic_settings import BaseSettings
from typing import Optional
import os
import secrets

class Settings(BaseSettings):
    # Proxy Configuration
    proxy_base_url: str = "http://localhost:8000"
    proxy_key: Optional[str] = None
    
    # Target Provider Configuration
    target_base_url: str = "https://api.openai.com"
    target_api_key: Optional[str] = None
    default_model: str = "gpt-4o-mini"
    
    # HTTP Configuration
    http_timeout_seconds: int = 60
    http_max_retries: int = 0
    stream_buffer_limit: int = 1048576  # 1MB
    
    # Database
    database_url: str = "sqlite:///./llm_relay.db"
    
    # Admin Dashboard
    admin_username: str = "admin"
    admin_password: str = "admin123"
    
    # Security
    secret_key: str = secrets.token_urlsafe(32)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Logging
    log_level: str = "INFO"
    redact_logs: bool = False
    
    # Rate Limiting
    rate_limit_per_minute: int = 60
    max_concurrent_requests: int = 100
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Generate proxy_key if not provided
        if not self.proxy_key:
            self.proxy_key = f"sk-proxy-{secrets.token_urlsafe(32)}"

settings = Settings()

# Configuration manager to handle database + env var precedence
class ConfigManager:
    def __init__(self, db_session=None):
        self.db_session = db_session
        self._cache = {}
    
    def get(self, key: str, default=None, force_env=False):
        # Priority: Database > Default (env vars only used with force_env=True or during init)
        
        # 1. Check database first (if session available and not forcing env)
        if self.db_session and not force_env:
            try:
                from app.models.models import Settings as DBSettings
                db_settings = self.db_session.query(DBSettings).first()
                if db_settings:
                    db_value = getattr(db_settings, key.lower(), None)
                    if db_value is not None:
                        return db_value
            except Exception:
                pass  # Database might not be initialized yet
        
        # 2. Check environment variable (fallback or when forced)
        env_value = os.getenv(key.upper())
        if env_value is not None:
            return env_value
        
        # 3. Return default value
        return getattr(settings, key.lower(), default)
    
    def get_proxy_config(self):
        return {
            "proxy_base_url": self.get("PROXY_BASE_URL"),
            "proxy_key": self.get("PROXY_KEY"),
        }
    
    def get_provider_config(self):
        return {
            "target_base_url": self.get("TARGET_BASE_URL"),
            "target_api_key": self.get("TARGET_API_KEY"),
            "default_model": self.get("DEFAULT_MODEL"),
            "http_timeout_seconds": int(self.get("HTTP_TIMEOUT_SECONDS")),
            "http_max_retries": int(self.get("HTTP_MAX_RETRIES")),
        }
    
    def clear_cache(self):
        self._cache.clear()
    
    def sync_env_to_database(self):
        """将环境变量同步到数据库（仅在初始化时使用）"""
        if not self.db_session:
            raise RuntimeError("Database session required for sync operation")
        
        try:
            from app.models.models import Settings as DBSettings
            
            # 获取现有数据库设置
            db_settings = self.db_session.query(DBSettings).first()
            if not db_settings:
                db_settings = DBSettings()
                self.db_session.add(db_settings)
            
            # 从环境变量更新每个字段
            env_mapping = {
                'proxy_base_url': 'PROXY_BASE_URL',
                'proxy_key': 'PROXY_KEY',
                'target_base_url': 'TARGET_BASE_URL',
                'target_api_key': 'TARGET_API_KEY',
                'default_model': 'DEFAULT_MODEL',
                'redact_logs': 'REDACT_LOGS',
                'http_timeout_seconds': 'HTTP_TIMEOUT_SECONDS',
                'http_max_retries': 'HTTP_MAX_RETRIES'
            }
            
            updated_fields = []
            for db_field, env_var in env_mapping.items():
                env_value = os.getenv(env_var)
                if env_value is not None:
                    # 类型转换
                    if db_field in ['redact_logs']:
                        env_value = env_value.lower() in ['true', '1', 'yes']
                    elif db_field in ['http_timeout_seconds', 'http_max_retries']:
                        env_value = int(env_value)
                    
                    setattr(db_settings, db_field, env_value)
                    updated_fields.append(f"{db_field}: {env_value}")
            
            if updated_fields:
                from datetime import datetime, timezone
                db_settings.updated_at = datetime.now(timezone.utc)
                self.db_session.commit()
                print(f"✅ 已同步环境变量到数据库:")
                for field in updated_fields:
                    print(f"  - {field}")
            else:
                print("ℹ️  没有找到需要同步的环境变量")
                
        except Exception as e:
            print(f"❌ 同步环境变量失败: {e}")
            self.db_session.rollback()
            raise

def get_config_manager(db_session=None) -> ConfigManager:
    return ConfigManager(db_session)