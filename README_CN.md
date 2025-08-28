# LLM Relay

**OpenAI 兼容的 LLM 应用开发监控代理服务**

LLM Relay 是一个全面的代理服务器，位于你的应用程序和 LLM 提供商之间，捕获详细的请求/响应数据，用于 LLM 应用的开发、调试和优化。

## 🎯 项目目的

本项目专为以下场景设计：
- **LLM 应用开发**: 在开发过程中监控真实的提示词和响应
- **提示词工程**: 基于实际使用数据分析和优化提示词
- **响应分析**: 跟踪模型行为、令牌使用和性能指标  
- **开发可观测性**: 全面了解 LLM 交互过程，便于调试

## ✨ 核心特性

### 🔄 **代理功能**
- **完全 OpenAI API 兼容**: OpenAI API 端点的直接替代品
- **多供应商支持**: 支持 OpenAI、Claude、通义千问等 OpenAI 兼容 API
- **流式传输支持**: 基于服务器发送事件(SSE)的实时响应流
- **多模态支持**: 完整的视觉语言模型(VLM)图像处理支持

### 📊 **全面日志记录**
- **完整请求/响应捕获**: 带 JSON 格式化的完整提示词和响应日志
- **流式聚合**: 智能重构来自流式数据块的完整响应
- **预览与完整存储**: 提供截断预览和完整内容两种查看方式
- **数据脱敏**: 自动检测和遮蔽敏感信息的 PII 保护

### 🎛️ **管理与监控**
- **Web 管理界面**: 直观的系统管理仪表板
- **API 密钥管理**: 安全的密钥生成、轮换和访问控制
- **实时日志**: 高级过滤、搜索和详细日志检查功能
- **性能指标**: Prometheus 兼容的指标和健康状态监控


### 🔐 **安全与配置**
- **安全 API 密钥**: SHA-256 哈希存储，仅显示前缀
- **JWT 认证**: 基于令牌的安全管理面板访问
- **运行时配置**: 数据库优先的配置，支持基于 Web 的管理
- **环境同步**: 从环境变量初始化数据库配置

## 🏗️ 系统架构

```
┌─────────────────────────┐
│    LLM 应用程序         │
│    (你的代码)           │
└──────────┬──────────────┘
           │ OpenAI API 调用
           ▼
┌─────────────────────────┐
│      LLM Relay          │
│  ┌─────────────────────┐│
│  │   日志记录 &        ││ ◄── Web 管理界面
│  │   监控系统          ││
│  └─────────────────────┘│
└──────────┬──────────────┘
           │ 转发请求
           ▼
┌─────────────────────────┐
│   LLM 服务提供商        │
│ (OpenAI/Claude/通义)    │
└─────────────────────────┘
```

## 🚀 快速开始

### 环境要求
- Python 3.8+
- pip 或 conda

### 安装步骤

1. **克隆仓库**
```bash
git clone <repository-url>
cd llm-relay
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置环境**
```bash
cp .env.example .env
# 编辑 .env 文件，设置你的配置：
# TARGET_API_KEY=你的供应商API密钥
# PROXY_KEY=你的自定义代理密钥
```

4. **初始化并启动**
```bash
# 使用环境变量初始化数据库
python run.py --init

# 启动服务器
python run.py
```

5. **访问系统**
- **API 端点**: `http://localhost:8000`
- **管理面板**: `http://localhost:8000/admin/login`
- **API 文档**: `http://localhost:8000/docs`

## 📖 使用方法

### 基础聊天补全

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR-PROXY-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "你好！"}],
    "temperature": 0.7
  }'
```

### 视觉语言模型 (VLM)

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR-PROXY-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-vl-plus",
    "messages": [{
        "role": "user",
        "content": [
         {"type": "image_url","image_url": {"url": "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"}},
         {"type": "text","text": " 图片中有几个人？"}
         ]}]
  }'
```

### Python 集成

```python
import openai

# 配置使用 LLM Relay
openai.api_base = "http://localhost:8000/v1"
openai.api_key = "YOUR-PROXY-KEY"

# 像使用 OpenAI 一样使用
response = openai.ChatCompletion.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "你好！"}],
    temperature=0.7
)

print(response.choices[0].message.content)
```

## 🔧 配置选项

### 环境变量

```bash
# 核心设置
PROXY_BASE_URL=http://localhost:8000    # 代理服务器地址
PROXY_KEY=sk-proxy-your-key            # API 访问密钥

# 目标供应商
TARGET_BASE_URL=https://api.openai.com # 供应商 API 端点
TARGET_API_KEY=sk-your-provider-key    # 供应商 API 密钥
DEFAULT_MODEL=gpt-4o-mini              # 默认模型名称

# 管理员访问
ADMIN_USERNAME=admin                   # 管理员登录用户名
ADMIN_PASSWORD=your-secure-password    # 管理员登录密码

# 可选设置
HTTP_TIMEOUT_SECONDS=60               # 请求超时时间
HTTP_MAX_RETRIES=0                    # 重试次数
REDACT_LOGS=false                     # 启用 PII 脱敏
DATABASE_URL=sqlite:///./llm_relay.db # 数据库连接
```

### 数据库初始化

```bash
# 将环境变量同步到数据库（首次运行）
python run.py --init
```

## 📊 管理面板功能

### 仪表板
- 系统状态概览
- 请求统计信息和成功率
- 动态端点的 API 使用示例

### 系统设置
- 运行时配置管理
- 供应商连接测试
- HTTP 超时和重试设置

### API 密钥管理
- 安全的密钥生成和显示
- 密钥状态管理（激活/停用）
- 到期时间设置

### 日志查看器
- 实时请求/响应监控
- 按日期、模型、状态、API 密钥进行高级过滤
- 带 JSON 格式化的完整消息内容检查
- 分析导出功能

## 🐳 Docker 部署

```bash
# 使用 Docker Compose 构建和运行
docker-compose up -d
```

服务将在 `http://localhost:8000` 可用

## 🔍 API 端点

### OpenAI 兼容 API
- `POST /v1/chat/completions` - 聊天补全（流式和非流式）
- `POST /v1/responses` - 响应 API
- `GET /v1/models` - 可用模型列表

### 管理 API
- `GET /admin/settings` - 获取系统设置
- `PUT /admin/settings` - 更新系统设置
- `GET /admin/api-keys` - 列出 API 密钥
- `POST /admin/api-keys` - 创建 API 密钥
- `GET /admin/logs` - 带过滤的日志查询
- `GET /admin/logs/{id}` - 获取详细日志条目

### 监控端点
- `GET /healthz` - 健康检查端点
- `GET /metrics` - Prometheus 指标

## 🛠️ 开发说明

### 项目结构
```
llm-relay/
├── app/                 # 核心应用程序
│   ├── api/            # API 路由处理器
│   ├── core/           # 配置和安全模块
│   ├── models/         # 数据库模型
│   ├── schemas/        # Pydantic 数据模式
│   └── services/       # 业务逻辑服务
├── templates/          # Web UI 模板
├── alembic/           # 数据库迁移
└── requirements.txt   # 依赖清单
```

### 核心组件

- **`app/main.py`** - FastAPI 应用程序和启动逻辑
- **`app/services/provider.py`** - 供应商通信的 HTTP 客户端
- **`app/services/logging.py`** - 请求/响应日志记录和聚合
- **`app/api/v1.py`** - OpenAI 兼容 API 实现
- **`app/api/admin.py`** - 管理 API 端点

## 📈 监控与指标

LLM Relay 通过以下方式提供全面监控：

- **健康检查**: `/healthz` 端点用于服务监控
- **Prometheus 指标**: `/metrics` 端点提供请求计数、延迟和错误率
- **结构化日志**: JSON 格式的日志，便于外部日志聚合
- **数据库分析**: 通过管理界面查询请求模式和使用统计

## 🔒 安全考虑

- **API 密钥哈希**: 所有 API 密钥都以 SHA-256 哈希存储
- **速率限制**: 每个 API 密钥的可配置速率限制
- **数据脱敏**: 日志中的可选 PII 遮蔽
- **安全头**: CORS 和安全头配置
- **JWT 令牌**: 有时限的管理员会话令牌

## 📈 使用场景

### LLM 应用开发
- 实时监控应用程序发送给 LLM 的实际提示词
- 观察不同参数设置对响应质量的影响
- 分析令牌使用情况，优化成本控制

### 提示词工程
- 收集真实用户交互数据，优化提示词模板
- A/B 测试不同的提示词策略
- 跟踪提示词变更对响应质量的影响

### 调试与优化
- 快速定位 LLM 调用中的问题
- 分析响应时间和成功率趋势
- 导出日志数据进行深入分析

## 🤝 贡献指南

1. Fork 仓库
2. 创建功能分支
3. 进行更改
4. 添加测试（如适用）
5. 提交拉取请求

## 📄 许可证

本项目基于 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🆘 技术支持

如有问题、功能请求或疑问：
1. 查看 [Issues](../../issues) 页面
2. 创建包含详细信息的新问题
3. 报告错误时请包含日志和配置信息（已脱敏）

---

**祝您 LLM 开发愉快！ 🚀**