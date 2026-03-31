# U-Finder 后端

![License](https://img.shields.io/badge/license-Apache%202.0-orange.svg)
![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green.svg)

🌍 [English](../../README.md) | **简体中文** | [繁體中文](../zh-tw/README.md)

U-Finder 的后端子模块，一个基于大语言模型的大学选择辅助系统，旨在帮助学生选择适合自己学术发展的大学。如需查看主项目，请访问 [GRP-Team202511/u-finder](https://github.com/GRP-Team202511/u-finder)。

## 目录

- [U-Finder 后端](#u-finder-后端)
  - [目录](#目录)
  - [关于](#关于)
  - [功能特性](#功能特性)
  - [技术栈](#技术栈)
  - [快速开始](#快速开始)
    - [环境要求](#环境要求)
    - [安装](#安装)
    - [开发](#开发)
    - [运行测试](#运行测试)
  - [项目结构](#项目结构)
  - [配置](#配置)
    - [环境变量](#环境变量)
  - [数据库模型](#数据库模型)
  - [贡献](#贡献)
  - [许可证](#许可证)

## 关于

U-Finder 后端是一个基于 FastAPI 和 Python 3.12 构建的异步 RESTful API 服务器。它为 U-Finder 平台提供用户认证、个人资料管理、通过 Dify 平台实现的 AI 聊天、简历解析、大学项目去重以及管理员仪表盘等功能，底层由 PostgreSQL 和 Redis 驱动。

## 功能特性

- **用户认证** - 支持邮箱/密码注册与登录，6 位数邮箱验证码
- **双因素认证 (2FA)** - 基于 TOTP 的双因素认证，支持二维码设置、备份码和 AES-256-GCM 加密密钥存储
- **Passkey / WebAuthn** - 符合 FIDO2 标准的免密认证
- **多设备会话管理** - 查看活跃会话、选择性登出和全设备登出
- **用户资料管理** - 基于 JSONB 的灵活用户资料，涵盖教育背景、学术成果、考试成绩、实习、项目、校园经历和获奖情况
- **简历上传与 AI 解析** - 上传 PDF/DOCX，通过 Dify AI 工作流解析并返回结构化资料数据
- **AI 聊天 (SSE 流式传输)** - 实时流式聊天代理，注入用户资料以提供个性化大学推荐
- **收藏大学项目** - 查看、收藏、取消收藏，支持两级去重（URL + 标准化名称）
- **管理员仪表盘** - 基于 JWT 的管理员认证（含超级管理员角色）、用户 KPI、LLM 成本监控（阿里云和腾讯云计费）、系统日志预览（支持分页）和用户管理（封禁/解封/删除）
- **LLM 用量记录** - 按请求记录 Token 和成本，覆盖聊天与简历解析工作流
- **后台清理** - 每小时自动清理过期令牌和失效 Redis 会话
- **反机器人保护** - 集成 Cloudflare Turnstile，保护注册、登录和密码重置端点
- **云服务计费监控** - 阿里云和腾讯云 API 费用追踪，用于管理员仪表盘
- **基于角色的访问控制** - 四种用户类型：学生 (1)、机构 (2)、管理员 (3)、超级管理员 (4)

## 技术栈

- **框架**: [FastAPI](https://fastapi.tiangolo.com/) 0.104 - 高性能异步 Python Web 框架
- **服务器**: [Uvicorn](https://www.uvicorn.org/) 0.24 - 高性能 ASGI 服务器
- **语言**: [Python](https://www.python.org/) 3.12
- **数据库**: [PostgreSQL](https://www.postgresql.org/) + [asyncpg](https://github.com/MagicStack/asyncpg) 0.30 异步驱动
- **ORM**: [SQLAlchemy](https://www.sqlalchemy.org/) 2.0（异步模式）
- **缓存**: [Redis](https://redis.io/) 5.2（异步） - 会话缓存、2FA 状态、WebAuthn 挑战
- **AI 集成**: [Dify](https://dify.ai/) - LLM 编排平台（聊天 Agent + 简历解析工作流）
- **HTTP 客户端**: [httpx](https://www.python-httpx.org/) 0.28 - 异步 HTTP 客户端，用于 Dify API 调用
- **认证**: [bcrypt](https://github.com/pyca/bcrypt)（密码哈希）、[PyJWT](https://pyjwt.readthedocs.io/)（管理员 JWT）、[pyotp](https://github.com/pyauth/pyotp)（TOTP）、[webauthn](https://github.com/duo-labs/py_webauthn) 2.7（Passkey）
- **加密**: [cryptography](https://cryptography.io/) - 用于 TOTP 密钥的 AES-256-GCM 加密
- **邮件**: [aiosmtplib](https://aiosmtplib.readthedocs.io/) - 异步 SMTP 邮件发送
- **图像处理**: [Pillow](https://pillow.readthedocs.io/) + [pillow-heif](https://github.com/bigcat88/pillow_heif) - 头像处理，支持 HEIC/HEIF 格式
- **数据验证**: [Pydantic](https://docs.pydantic.dev/) 2.12 + [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) - 数据验证与环境配置
- **测试**: [pytest](https://docs.pytest.org/) + [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) + [pytest-cov](https://github.com/pytest-dev/pytest-cov) + [httpx](https://www.python-httpx.org/)（ASGITransport）
- **CI/CD**: [GitHub Actions](https://github.com/features/actions) - 推送/PR 时自动运行测试，CD 测试环境与生产环境部署
- **容器化**: [Docker](https://www.docker.com/) + [Docker Compose](https://docs.docker.com/compose/) - 容器化部署，包含 PostgreSQL 和 Redis
- **反机器人**: [Cloudflare Turnstile](https://www.cloudflare.com/products/turnstile/) - 认证端点的机器人防护

## 快速开始

### 环境要求

在开始之前，请确保已安装以下软件：

- **Python**（v3.12 或更高版本）
- **pip**（建议使用最新版本）
- **Docker** 与 **Docker Compose** - 用于运行 PostgreSQL 和 Redis。请在 U-Finder 主仓库的 [`database/`](https://github.com/GRP-Team202511/u-finder/tree/main/database) 目录下执行 `docker compose up -d` 启动。

### 安装

1. 克隆仓库（如果尚未克隆主 U-Finder 项目）：

```bash
git clone --recursive https://github.com/GRP-Team202511/u-finder
cd u-finder/backend
```

> 如果克隆时未使用 `--recursive`，请手动初始化子模块：
> ```bash
> git submodule update --init --recursive
> ```

2. 创建并激活虚拟环境：

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

3. 安装依赖：

```bash
pip install -r requirements.txt
```

4. 配置环境变量：

```bash
cp .env.example .env
# 编辑 .env，填入数据库、Redis、Dify 和 SMTP 凭据
```

5. 通过 Docker Compose 启动 PostgreSQL 和 Redis（在 U-Finder 主仓库的 `database/` 目录下执行）：

```bash
cd ../database
docker compose up -d
cd ../backend
```

数据库表会在首次启动时通过 SQLAlchemy 的 `create_all()` 自动创建。

### 开发

启动开发服务器：

```bash
python run.py
```

API 将在 `http://localhost:8000` 上可用。完整 API 文档请参阅 [Apifox](https://bop63bqzti.apifox.cn)。

### 运行测试

运行完整测试套件（含覆盖率）：

```bash
pytest --cov=src --cov-report=term-missing
```

运行指定测试文件：

```bash
pytest tests/routers/test_auth_login.py -v
```

## 项目结构

```
backend/
├── app/
│   └── main.py                  # FastAPI 应用入口，生命周期管理，中间件
├── run.py                       # Uvicorn 启动脚本
├── src/
│   ├── config/
│   │   ├── settings.py          # 基于 Pydantic-settings 的配置管理
│   │   ├── constants.py         # UserType 与 TokenType 枚举
│   │   └── logger.py            # RotatingFileHandler 日志配置
│   ├── database/
│   │   ├── connection.py        # 异步 SQLAlchemy 引擎与会话工厂
│   │   ├── redis_connection.py  # 异步 Redis 客户端管理
│   │   └── models.py            # ORM 模型（9 张表）
│   ├── routers/
│   │   ├── auth.py              # 认证端点（注册、登录、重置等）
│   │   ├── two_factor.py        # 2FA 端点（设置、确认、验证、禁用）
│   │   ├── passkey.py           # WebAuthn 端点（注册、登录）
│   │   ├── profile.py           # 个人资料、头像与收藏大学端点
│   │   ├── chat.py              # AI 聊天 SSE 流式传输与会话管理
│   │   └── admin.py             # 管理员仪表盘与用户管理
│   ├── schemas/
│   │   ├── auth.py              # 认证请求/响应模型
│   │   ├── two_factor.py        # 2FA 请求/响应模型
│   │   ├── passkey.py           # Passkey 请求/响应模型
│   │   ├── profile.py           # 个人资料与大学项目模型
│   │   ├── chat.py              # 聊天与会话模型
│   │   └── admin.py             # 管理员仪表盘模型
│   ├── services/
│   │   ├── dify_service.py      # Dify AI API 集成（聊天、简历解析、反馈）
│   │   ├── university_service.py # 大学项目去重
│   │   ├── llm_usage_service.py # LLM 用量与成本记录
│   │   ├── aliyun_billing_service.py  # 阿里云计费 API
│   │   └── tencent_billing_service.py # 腾讯云计费 API
│   ├── utils/
│   │   ├── jwt_utils.py         # JWT 创建、验证、临时令牌
│   │   ├── password_utils.py    # bcrypt 哈希、HMAC-SHA256 令牌哈希
│   │   ├── totp_utils.py        # TOTP 生成、AES-GCM 加密、二维码
│   │   ├── email_utils.py       # 异步 SMTP 邮件与 HTML 模板
│   │   ├── session_utils.py     # Redis 会话 CRUD（Cache-Aside 模式）
│   │   ├── auth_deps.py         # 共享认证依赖（get_current_user_id）
│   │   ├── cleanup.py           # 过期令牌清理工具
│   │   └── turnstile.py         # Cloudflare Turnstile 验证
│   └── templates/
│       └── emails/              # HTML 邮件模板
│           ├── verification-email.html
│           ├── resetpassword-email.html
│           └── delete-account-email.html
├── tests/
│   ├── conftest.py              # 测试夹具、Mock DB/Redis、假数据工厂
│   ├── unit/                    # 单元测试（工具类、Schema、服务）
│   ├── routers/                 # 路由级测试（按端点划分）
│   │   └── utils/
│   │       └── response_asserts.py  # 可复用响应 Schema 验证器
│   └── integration/             # 端到端工作流测试
├── scripts/
│   └── test_2fa_manual.py       # 手动 2FA 生命周期测试脚本
├── docker/
│   └── db/
│       └── init.sql             # PostgreSQL 架构初始化
├── .github/
│   └── workflows/
│       ├── ci.yml               # GitHub Actions CI 流水线
│       ├── cd-staging.yml       # CD 测试环境部署
│       ├── cd-production.yml    # CD 生产环境部署
│       └── docker-build.yml     # Docker 镜像构建工作流
├── Dockerfile                   # 生产环境 Docker 镜像
├── docker-compose.yml           # 本地开发服务
├── docker-compose.prod.yml      # 生产环境 Docker Compose
├── .env.example                 # 环境变量模板
├── requirements.txt             # Python 依赖
├── pytest.ini                   # pytest 配置
└── .gitignore
```

## 配置

### 环境变量

将 `.env.example` 复制为 `.env` 并配置以下内容：

```env
# 应用
APP_NAME=U-Finder Backend
ENVIRONMENT=development          # development | staging | production

# 服务器
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# 数据库
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/u_finder

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# 安全
SECRET_KEY=your-secret-key       # 用于 JWT 签名和 HMAC 令牌哈希

# Dify AI
DIFY_API_BASE_URL=https://api.dify.ai/v1
DIFY_API_KEY=app-your-chat-key
DIFY_WORKFLOW_API_KEY=app-your-workflow-key

# 邮件 (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email
SMTP_PASSWORD=your-app-password

# 2FA 加密
TOTP_ENCRYPTION_KEY=base64-encoded-32-byte-key

# WebAuthn / Passkey
WEBAUTHN_RP_ID=localhost
WEBAUTHN_ORIGIN=http://localhost:3000
```

完整变量列表及说明请参见 [`.env.example`](../../.env.example)。

## 数据库模型

后端使用 9 张 PostgreSQL 表：

| 表名 | 用途 |
|------|------|
| `account` | 用户账户（邮箱、密码哈希、用户类型、2FA 标志） |
| `user_profile` | 基于 JSONB 的灵活用户资料（教育、考试、获奖等） |
| `refresh_token` | 会话令牌，附带设备 User-Agent 追踪 |
| `temp_token` | 临时令牌，用于邮箱验证、密码重置、2FA、账户删除 |
| `totp_backup_code` | 经哈希处理的一次性备份码，用于 2FA 恢复 |
| `passkey` | WebAuthn/FIDO2 凭据存储 |
| `university_program` | 去重后的大学项目实体（JSONB 项目数据） |
| `user_liked_university` | 用户 ↔ 收藏项目关联表 |
| `llm_usage_log` | 按请求记录的 LLM 用量（Token、成本、延迟） |

## 贡献

欢迎贡献！更多信息请参阅主仓库的贡献指南。

## 许可证

本项目是 U-Finder 系统的一部分，许可证信息请参阅主仓库。
