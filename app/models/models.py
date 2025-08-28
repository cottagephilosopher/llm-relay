from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
from app.db.base import Base

class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    proxy_base_url = Column(String(255), nullable=False)
    proxy_key = Column(String(255), nullable=False)
    target_base_url = Column(String(255), nullable=False, default="https://api.openai.com")
    target_api_key = Column(String(255), nullable=False)
    default_model = Column(String(100), nullable=False, default="gpt-4o-mini")
    redact_logs = Column(Boolean, default=False)
    http_timeout_seconds = Column(Integer, default=60)
    http_max_retries = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class ApiKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    key_prefix = Column(String(20), nullable=False)
    status = Column(String(20), default="active", index=True)
    expire_at = Column(DateTime, nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    logs = relationship("Log", back_populates="api_key")

class Log(Base):
    __tablename__ = "logs"
    
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    finished_at = Column(DateTime, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    route = Column(String(100), nullable=False, index=True)
    method = Column(String(10), nullable=False)
    client_api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=True, index=True)
    provider_base_url = Column(String(255), nullable=False)
    provider_model = Column(String(100), nullable=True, index=True)
    request_headers_hash = Column(String(64), nullable=True)
    request_body_preview = Column(Text, nullable=True)
    request_body_full = Column(Text, nullable=True)
    response_body_preview = Column(Text, nullable=True)
    response_body_full = Column(Text, nullable=True)
    streamed = Column(Boolean, default=False, index=True)
    proxy_status = Column(Integer, nullable=True, index=True)
    provider_status = Column(Integer, nullable=True, index=True)
    error_code = Column(String(50), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    token_usage_prompt = Column(Integer, nullable=True)
    token_usage_completion = Column(Integer, nullable=True)
    token_usage_total = Column(Integer, nullable=True)
    cost_estimated = Column(Float, nullable=True)
    truncated = Column(Boolean, default=False)
    partial = Column(Boolean, default=False)
    
    api_key = relationship("ApiKey", back_populates="logs")
    chunks = relationship("LogChunk", back_populates="log", cascade="all, delete-orphan")

class LogChunk(Base):
    __tablename__ = "log_chunks"
    
    id = Column(Integer, primary_key=True, index=True)
    log_id = Column(Integer, ForeignKey("logs.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    log = relationship("Log", back_populates="chunks")