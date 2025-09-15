# LLM Relay

**A OpenAI-compatible proxy for LLM application development and monitoring**

LLM Relay is a comprehensive proxy server that sits between your application and LLM providers, capturing detailed request/response data for development, debugging, and optimization of LLM applications.

## 🎯 Purpose

This project is specifically designed for:
- **LLM Application Development**: Monitor real prompts and responses during development
- **Prompt Engineering**: Analyze and optimize prompts based on actual usage data  
- **Response Analysis**: Track model behaviors, token usage, and performance metrics
- **Development Observability**: Full visibility into LLM interactions for debugging

## ✨ Features

### 🔄 **Proxy Functionality**
- **Full OpenAI API Compatibility**: Drop-in replacement for OpenAI API endpoints
- **Multi-Provider Support**: Works with OpenAI, Claude, Qwen, and other OpenAI-compatible APIs
- **Streaming Support**: Real-time response streaming with Server-Sent Events (SSE)
- **VLM Support**: Complete vision-language model support for image processing

### 📊 **Comprehensive Logging**
- **Complete Request/Response Capture**: Full prompt and response logging with JSON formatting
- **Streaming Aggregation**: Intelligently reconstructs complete responses from streaming chunks
- **Content Preview & Full Storage**: Both truncated previews and complete content available
- **Data Redaction**: Automatic PII detection and masking for sensitive information

### 🎛️ **Management & Monitoring**
- **Web Management Interface**: Intuitive dashboard for system administration
- **API Key Management**: Secure key generation, rotation, and access control
- **Real-time Logs**: Advanced filtering, searching, and detailed log inspection
- **Performance Metrics**: Prometheus-compatible metrics and health monitoring

### 🔐 **Security & Configuration**
- **Secure API Keys**: SHA-256 hashed storage with prefix display
- **JWT Authentication**: Secure admin panel access with token-based auth
- **Runtime Configuration**: Database-first config with web-based management
- **Environment Sync**: Initialize database config from environment variables

## 🏗️ Architecture

```
┌─────────────────────────┐
│   LLM Application       │
│   (Your Code)           │
└──────────┬──────────────┘
           │ OpenAI API calls
           ▼
┌─────────────────────────┐
│      LLM Relay          │
│  ┌─────────────────────┐│
│  │   Logging &         ││ ◄── Web Admin Interface
│  │   Monitoring        ││
│  └─────────────────────┘│
└──────────┬──────────────┘
           │ Forwards requests
           ▼
┌─────────────────────────┐
│   LLM Provider          │
│ (OpenAI/Claude/Qwen)    │
└─────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- pip or conda

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd llm-relay
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your settings:
# TARGET_API_KEY=your-provider-api-key
# PROXY_KEY=your-custom-proxy-key
```

4. **Initialize and start**
```bash
# Initialize database with environment variables
python run.py --init

# Start the server
python run.py
```

5. **Access the system**
- **API Endpoint**: `http://localhost:11438`
- **Admin Panel**: `http://localhost:11438/admin/login`
- **API Documentation**: `http://localhost:11438/docs`

## 📖 Usage

### Basic Chat Completion

```bash
curl -X POST http://localhost:11438/v1/chat/completions \
  -H "Authorization: Bearer YOUR-PROXY-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7
  }'
```

### Vision Language Model (VLM)

```bash
curl -X POST http://localhost:11438/v1/chat/completions \
  -H "Authorization: Bearer YOUR-PROXY-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-vl-plus",
    "messages": [{
        "role": "user",
        "content": [
         {"type": "image_url","image_url": {"url": "https://example.com/image.jpg"}},
         {"type": "text","text": "What do you see in this image?"}
         ]}]
  }'
```

### Python Integration

```python
import openai

# Configure to use LLM Relay
openai.api_base = "http://localhost:11438/v1"
openai.api_key = "YOUR-PROXY-KEY"

# Use exactly as you would with OpenAI
response = openai.ChatCompletion.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello!"}],
    temperature=0.7
)

print(response.choices[0].message.content)
```

## 🔧 Configuration

### Environment Variables

```bash
# Core Settings
PROXY_BASE_URL=http://localhost:11438    # Proxy server address
PROXY_KEY=sk-proxy-your-key            # API access key

# Target Provider
TARGET_BASE_URL=https://api.openai.com # Provider API endpoint
TARGET_API_KEY=sk-your-provider-key    # Provider API key
DEFAULT_MODEL=gpt-4o-mini              # Default model name

# Admin Access
ADMIN_USERNAME=admin                   # Admin login username
ADMIN_PASSWORD=your-secure-password    # Admin login password

# Optional Settings
HTTP_TIMEOUT_SECONDS=60               # Request timeout
HTTP_MAX_RETRIES=0                    # Retry attempts
REDACT_LOGS=false                     # Enable PII redaction
DATABASE_URL=sqlite:///./llm_relay.db # Database connection
```

### Database Initialization

```bash
# Sync environment variables to database (run once)
python run.py --init
```

## 📊 Admin Panel Features

### Dashboard
- System status overview
- Request statistics and success rates
- API usage examples with dynamic endpoints

### System Settings
- Runtime configuration management
- Provider connection testing
- HTTP timeout and retry settings

### API Key Management
- Secure key generation and display
- Key status management (active/inactive)
- Expiration date settings

### Log Viewer
- Real-time request/response monitoring
- Advanced filtering by date, model, status, API key
- Complete message content inspection with JSON formatting
- Export functionality for analysis

## 🐳 Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up -d
```

The service will be available at `http://localhost:11438`

## 🔍 API Endpoints

### OpenAI Compatible APIs
- `POST /v1/chat/completions` - Chat completions (streaming & non-streaming)
- `POST /v1/responses` - Response API
- `GET /v1/models` - Available models list

### Management APIs
- `GET /admin/settings` - Get system settings
- `PUT /admin/settings` - Update system settings
- `GET /admin/api-keys` - List API keys
- `POST /admin/api-keys` - Create API key
- `GET /admin/logs` - Query logs with filtering
- `GET /admin/logs/{id}` - Get detailed log entry

### Monitoring
- `GET /healthz` - Health check endpoint
- `GET /metrics` - Prometheus metrics

## 🛠️ Development

### Project Structure
```
llm-relay/
├── app/                 # Core application
│   ├── api/            # API route handlers
│   ├── core/           # Configuration and security
│   ├── models/         # Database models
│   ├── schemas/        # Pydantic data schemas
│   └── services/       # Business logic services
├── templates/          # Web UI templates
├── alembic/           # Database migrations
└── requirements.txt   # Dependencies
```

### Key Components

- **`app/main.py`** - FastAPI application and startup logic
- **`app/services/provider.py`** - HTTP client for provider communication
- **`app/services/logging.py`** - Request/response logging and aggregation
- **`app/api/v1.py`** - OpenAI-compatible API implementation
- **`app/api/admin.py`** - Management API endpoints

## 📈 Monitoring & Metrics

LLM Relay provides comprehensive monitoring through:

- **Health Checks**: `/healthz` endpoint for service monitoring
- **Prometheus Metrics**: `/metrics` endpoint with request counts, latencies, and error rates
- **Structured Logging**: JSON-formatted logs for external log aggregation
- **Database Analytics**: Query request patterns and usage statistics through admin interface

## 🔒 Security Considerations

- **API Key Hashing**: All API keys are stored as SHA-256 hashes
- **Rate Limiting**: Configurable rate limits per API key
- **Data Redaction**: Optional PII masking in logs
- **Secure Headers**: CORS and security headers configuration
- **JWT Tokens**: Time-limited admin session tokens

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

For issues, feature requests, or questions:
1. Check the [Issues](../../issues) page
2. Create a new issue with detailed information
3. Include logs and configuration (redacted) when reporting bugs

---

**Happy LLM Development! 🚀**