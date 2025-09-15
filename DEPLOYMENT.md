# Deployment Guide

This guide covers production deployment of the LLM Relay proxy server.

## Pre-deployment Checklist

- [ ] Configure production environment variables
- [ ] Change default admin credentials
- [ ] Set up SSL/TLS certificates
- [ ] Plan database backup strategy
- [ ] Set up monitoring and alerting
- [ ] Configure log rotation
- [ ] Test API endpoints and admin dashboard

## Environment Setup

### 1. Production Environment Variables

Create a production `.env` file:

```bash
# Server Configuration
PROXY_BASE_URL=https://your-domain.com
PROXY_KEY=sk-proxy-production-secure-key-here

# Provider Configuration
TARGET_BASE_URL=https://api.openai.com
TARGET_API_KEY=sk-your-production-openai-key
DEFAULT_MODEL=gpt-4o-mini

# Security
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-very-secure-password-here
SECRET_KEY=your-jwt-secret-key-32-chars-minimum

# Database
DATABASE_URL=postgresql://user:password@localhost/llm_relay
# OR for SQLite: sqlite:///./data/llm_relay.db

# Performance & Limits
HTTP_TIMEOUT_SECONDS=120
HTTP_MAX_RETRIES=1
RATE_LIMIT_PER_MINUTE=100
MAX_CONCURRENT_REQUESTS=50

# Logging & Privacy
LOG_LEVEL=INFO
REDACT_LOGS=true
STREAM_BUFFER_LIMIT=2097152

# System
WORKERS=4
```

### 2. Database Setup

#### SQLite (Simple Deployment)

```bash
# Create data directory
mkdir -p /app/data

# Set proper permissions
chmod 755 /app/data

# Initialize database
alembic upgrade head
```

#### PostgreSQL (Recommended for Production)

```bash
# Install PostgreSQL
sudo apt update
sudo apt install postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql
CREATE DATABASE llm_relay;
CREATE USER llm_relay_user WITH ENCRYPTED PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE llm_relay TO llm_relay_user;
\q

# Install Python driver
pip install psycopg2-binary

# Run migrations
DATABASE_URL=postgresql://llm_relay_user:secure_password@localhost/llm_relay alembic upgrade head
```

## Deployment Options

### Option 1: Docker Deployment

#### Dockerfile

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

# Expose port
EXPOSE 11438

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:11438/healthz || exit 1

# Start application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "11438", "--workers", "4"]
```

#### Docker Compose

```yaml
version: '3.8'

services:
  llm-relay:
    build: .
    container_name: llm-relay
    restart: unless-stopped
    ports:
      - "11438:11438"
    environment:
      - DATABASE_URL=postgresql://llm_relay_user:secure_password@db:5432/llm_relay
      - TARGET_API_KEY=${TARGET_API_KEY}
      - PROXY_KEY=${PROXY_KEY}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD}
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    depends_on:
      - db
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11438/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

  db:
    image: postgres:15-alpine
    container_name: llm-relay-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: llm_relay
      POSTGRES_USER: llm_relay_user
      POSTGRES_PASSWORD: secure_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backups:/backups
    ports:
      - "5432:5432"

  nginx:
    image: nginx:alpine
    container_name: llm-relay-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./nginx/ssl:/etc/nginx/ssl
    depends_on:
      - llm-relay

volumes:
  postgres_data:
```

#### Start with Docker Compose

```bash
# Copy environment file
cp .env.example .env
# Edit .env with production values

# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f llm-relay
```

### Option 2: Systemd Service

#### Create Service File

```bash
sudo tee /etc/systemd/system/llm-relay.service > /dev/null <<EOF
[Unit]
Description=LLM Relay Proxy Server
After=network.target

[Service]
Type=exec
User=llm-relay
Group=llm-relay
WorkingDirectory=/opt/llm-relay
Environment=PATH=/opt/llm-relay/venv/bin
EnvironmentFile=/opt/llm-relay/.env
ExecStart=/opt/llm-relay/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 11438 --workers 4
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

#### Installation Steps

```bash
# Create user and directories
sudo useradd --system --shell /bin/false llm-relay
sudo mkdir -p /opt/llm-relay
sudo chown llm-relay:llm-relay /opt/llm-relay

# Copy application
sudo cp -r . /opt/llm-relay/
sudo chown -R llm-relay:llm-relay /opt/llm-relay

# Create virtual environment
cd /opt/llm-relay
sudo -u llm-relay python -m venv venv
sudo -u llm-relay venv/bin/pip install -r requirements.txt

# Create environment file
sudo -u llm-relay cp .env.example .env
# Edit .env with production values

# Initialize database
sudo -u llm-relay venv/bin/alembic upgrade head

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable llm-relay
sudo systemctl start llm-relay

# Check status
sudo systemctl status llm-relay
```

## Reverse Proxy Setup

### Nginx Configuration

```nginx
# /etc/nginx/sites-available/llm-relay
upstream llm_relay {
    server localhost:11438;
    # Add more servers for load balancing
    # server localhost:8001;
    # server localhost:8002;
}

# Rate limiting
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req_zone $http_authorization zone=auth:10m rate=30r/s;

server {
    listen 80;
    server_name your-domain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL Configuration
    ssl_certificate /etc/ssl/certs/your-domain.com.pem;
    ssl_certificate_key /etc/ssl/private/your-domain.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Logging
    access_log /var/log/nginx/llm-relay.access.log;
    error_log /var/log/nginx/llm-relay.error.log;

    # Basic rate limiting
    limit_req zone=api burst=20 nodelay;

    # API endpoints
    location /v1/ {
        # Enhanced rate limiting for API endpoints
        limit_req zone=auth burst=50 nodelay;
        
        proxy_pass http://llm_relay;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts for potentially long-running requests
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        
        # Enable streaming
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # Admin endpoints (additional security)
    location /admin/ {
        # Restrict to specific IPs
        allow 192.168.1.0/24;  # Office network
        allow 10.0.0.0/8;      # VPN
        deny all;
        
        proxy_pass http://llm_relay;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Metrics endpoint (restrict access)
    location /metrics {
        allow 127.0.0.1;       # Localhost only
        allow 10.0.0.0/8;      # Internal network
        deny all;
        
        proxy_pass http://llm_relay;
        proxy_set_header Host $http_host;
    }

    # Health check
    location /healthz {
        proxy_pass http://llm_relay;
        access_log off;
    }

    # Root redirect
    location = / {
        return 301 https://$server_name/admin/dashboard;
    }
}
```

#### Enable Nginx Configuration

```bash
# Link configuration
sudo ln -s /etc/nginx/sites-available/llm-relay /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### Caddy Configuration (Alternative)

```caddyfile
# Caddyfile
your-domain.com {
    reverse_proxy localhost:11438
    
    # Rate limiting
    rate_limit {
        zone static 10r/s 100
    }
    
    # Security headers
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        X-XSS-Protection "1; mode=block"
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        -Server
    }

    # Admin path restrictions
    @admin path /admin/*
    handle @admin {
        # IP filtering can be added here
        reverse_proxy localhost:11438
    }
    
    # API endpoints
    handle /v1/* {
        reverse_proxy localhost:11438 {
            # Enable streaming
            flush_interval -1
        }
    }
    
    # Metrics (internal only)
    @metrics path /metrics
    handle @metrics {
        # Add IP restrictions
        reverse_proxy localhost:11438
    }
}
```

## SSL/TLS Certificates

### Let's Encrypt with Certbot

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal (already set up by certbot)
sudo systemctl status certbot.timer
```

### Self-signed Certificate (Development/Internal)

```bash
# Generate certificate
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/llm-relay.key \
    -out /etc/ssl/certs/llm-relay.crt

# Set permissions
sudo chmod 600 /etc/ssl/private/llm-relay.key
sudo chmod 644 /etc/ssl/certs/llm-relay.crt
```

## Monitoring and Alerting

### Prometheus Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'llm-relay'
    static_configs:
      - targets: ['localhost:11438']
    metrics_path: /metrics
    scrape_interval: 30s
```

### Grafana Dashboard

Import the provided Grafana dashboard JSON or create custom panels for:

- Request rate and response time
- Error rates by endpoint
- Token usage statistics
- Active streaming sessions
- System resources (CPU, memory)

### Basic Alerting

```yaml
# alerting.yml
groups:
  - name: llm-relay
    rules:
      - alert: HighErrorRate
        expr: rate(llm_relay_requests_total{status_code=~"5.."}[5m]) > 0.1
        for: 2m
        annotations:
          summary: "High error rate detected"
          
      - alert: HighLatency
        expr: histogram_quantile(0.95, llm_relay_request_duration_seconds) > 30
        for: 5m
        annotations:
          summary: "High latency detected"
```

## Backup Strategy

### Database Backup

#### PostgreSQL

```bash
#!/bin/bash
# backup-db.sh
BACKUP_DIR="/backups/postgresql"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_NAME="llm_relay"

mkdir -p $BACKUP_DIR

pg_dump -h localhost -U llm_relay_user $DB_NAME > "$BACKUP_DIR/llm_relay_$TIMESTAMP.sql"

# Keep only last 7 days
find $BACKUP_DIR -name "llm_relay_*.sql" -mtime +7 -delete

# Crontab entry: 0 2 * * * /opt/llm-relay/backup-db.sh
```

#### SQLite

```bash
#!/bin/bash
# backup-sqlite.sh
BACKUP_DIR="/backups/sqlite"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_PATH="/opt/llm-relay/llm_relay.db"

mkdir -p $BACKUP_DIR

cp "$DB_PATH" "$BACKUP_DIR/llm_relay_$TIMESTAMP.db"
gzip "$BACKUP_DIR/llm_relay_$TIMESTAMP.db"

# Keep only last 7 days
find $BACKUP_DIR -name "llm_relay_*.db.gz" -mtime +7 -delete
```

## Security Hardening

### 1. Firewall Configuration

```bash
# UFW (Ubuntu)
sudo ufw allow ssh
sudo ufw allow 80
sudo ufw allow 443
sudo ufw deny 11438  # Block direct access to app
sudo ufw --force enable
```

### 2. Fail2Ban Protection

```ini
# /etc/fail2ban/jail.local
[llm-relay]
enabled = true
port = 80,443
filter = llm-relay
logpath = /var/log/nginx/llm-relay.access.log
maxretry = 10
findtime = 600
bantime = 3600
```

```ini
# /etc/fail2ban/filter.d/llm-relay.conf
[Definition]
failregex = ^<HOST> .* "(POST|GET) /v1/.* HTTP/.*" 4(01|03|29) .*$
ignoreregex =
```

### 3. API Key Rotation

```bash
#!/bin/bash
# rotate-keys.sh
# Script to rotate API keys regularly

# Generate new key via admin API
NEW_KEY=$(curl -s -X POST -u admin:password \
  -H "Content-Type: application/json" \
  -d '{"name": "Rotated Key"}' \
  http://localhost:11438/admin/api-keys | jq -r '.full_key')

echo "New API key generated: $NEW_KEY"
echo "Remember to update your applications!"
```

## Performance Tuning

### 1. Application Settings

```bash
# High-throughput configuration
WORKERS=8
HTTP_TIMEOUT_SECONDS=30
RATE_LIMIT_PER_MINUTE=200
MAX_CONCURRENT_REQUESTS=100
STREAM_BUFFER_LIMIT=1048576
```

### 2. Database Optimization

#### PostgreSQL

```sql
-- Optimize PostgreSQL for logging workload
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
SELECT pg_reload_conf();
```

#### SQLite

```python
# In production, consider these PRAGMA settings
# Add to database initialization
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;  # 64MB cache
PRAGMA temp_store = memory;
```

### 3. System-level Optimization

```bash
# Increase file descriptor limits
echo "* soft nofile 65535" >> /etc/security/limits.conf
echo "* hard nofile 65535" >> /etc/security/limits.conf

# Optimize network settings
echo "net.core.somaxconn = 65535" >> /etc/sysctl.conf
echo "net.ipv4.tcp_max_syn_backlog = 65535" >> /etc/sysctl.conf
sysctl -p
```

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Check connection string format
   - Verify database user permissions
   - Ensure database server is running

2. **SSL Certificate Issues**
   - Verify certificate paths in Nginx config
   - Check certificate validity: `openssl x509 -in cert.pem -text -noout`
   - Ensure proper file permissions

3. **High Memory Usage**
   - Monitor streaming sessions with `/metrics`
   - Reduce `STREAM_BUFFER_LIMIT`
   - Enable log redaction to reduce memory usage

4. **Rate Limiting Issues**
   - Check current limits in admin dashboard
   - Monitor metrics for 429 responses
   - Adjust per-key limits if needed

### Log Analysis

```bash
# Check application logs
sudo journalctl -u llm-relay -f

# Check Nginx logs
sudo tail -f /var/log/nginx/llm-relay.access.log
sudo tail -f /var/log/nginx/llm-relay.error.log

# Docker logs
docker-compose logs -f llm-relay
```

### Performance Monitoring

```bash
# System resources
htop
iotop
netstat -tulpn

# Database performance
# PostgreSQL
sudo -u postgres psql -c "SELECT * FROM pg_stat_activity;"

# Application metrics
curl http://localhost:11438/metrics
curl http://localhost:11438/healthz
```

This deployment guide provides a comprehensive approach to running LLM Relay in production with proper security, monitoring, and performance considerations.