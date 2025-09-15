#!/usr/bin/env python3
"""
LLM Relay startup script
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def check_requirements():
    """Check if all requirements are installed"""
    try:
        import fastapi
        import uvicorn
        import sqlalchemy
        import httpx
        return True
    except ImportError as e:
        print(f"Missing requirement: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def check_database():
    """Check if database is initialized"""
    db_path = Path("llm_relay.db")
    if not db_path.exists():
        print("Database not found. Initializing...")
        try:
            from app.db.base import engine, Base
            Base.metadata.create_all(bind=engine)
            print("Database initialized successfully.")
            return True
        except Exception as e:
            print(f"Failed to initialize database: {e}")
            return False
    return True

def check_config():
    """Check basic configuration"""
    # Check if we have config either in env or database
    from app.db.base import SessionLocal
    from app.core.config import get_config_manager
    
    db = SessionLocal()
    try:
        config_manager = get_config_manager(db)
        target_api_key = config_manager.get("TARGET_API_KEY")
        
        if not target_api_key:
            print("Missing TARGET_API_KEY in both environment and database.")
            print("Please set TARGET_API_KEY in .env file or use --init to sync from environment.")
            return False
        
        return True
    finally:
        db.close()

def init_database_from_env():
    """初始化数据库配置（从环境变量同步）"""
    print("正在从环境变量初始化数据库配置...")
    
    from app.db.base import SessionLocal
    from app.core.config import get_config_manager
    
    db = SessionLocal()
    try:
        config_manager = get_config_manager(db)
        config_manager.sync_env_to_database()
        print("✅ 配置初始化完成！")
        return True
    except Exception as e:
        print(f"❌ 配置初始化失败: {e}")
        return False
    finally:
        db.close()

def run_server(host="127.0.0.1", port=11438, workers=1, reload=False):
    """Run the server"""
    print(f"Starting LLM Relay server on {host}:{port}")
    print(f"Workers: {workers}")
    print(f"Reload: {reload}")
    print("Press Ctrl+C to stop")
    
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", host,
        "--port", str(port),
    ]
    
    if workers > 1:
        cmd.extend(["--workers", str(workers)])
    
    if reload:
        cmd.append("--reload")
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\nShutting down server...")

def main():
    parser = argparse.ArgumentParser(description="LLM Relay Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=11438, help="Port to bind to")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--skip-checks", action="store_true", help="Skip startup checks")
    parser.add_argument("--init", action="store_true", help="Initialize database config from environment variables")
    
    args = parser.parse_args()
    
    # Handle --init flag
    if args.init:
        print("初始化模式：将环境变量同步到数据库...")
        if not check_requirements():
            sys.exit(1)
        if not check_database():
            sys.exit(1)
        if init_database_from_env():
            print("✅ 初始化完成！现在可以正常启动服务。")
        sys.exit(0)
    
    if not args.skip_checks:
        print("Performing startup checks...")
        
        if not check_requirements():
            sys.exit(1)
        
        if not check_database():
            sys.exit(1)
        
        if not check_config():
            sys.exit(1)
        
        print("All checks passed!")
        print()
    
    run_server(
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload
    )

if __name__ == "__main__":
    main()