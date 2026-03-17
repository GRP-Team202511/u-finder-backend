# U-Finder Backend

![License](https://img.shields.io/badge/license-Apache%202.0-orange.svg)
![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green.svg)

🌍 **English** | [简体中文](./docs/zh-cn/README.md) | [繁體中文](./docs/zh-tw/README.md)

The backend submodule for U-Finder, an LLM-based university finder system designed to assist students in selecting the right university for their academic journey. If you want to view the main project, please go to [GRP-Team202511/u-finder](https://github.com/GRP-Team202511/u-finder).

## Table of Contents

- [U-Finder Backend](#u-finder-backend)
  - [Table of Contents](#table-of-contents)
  - [About](#about)
  - [Features](#features)
  - [Tech Stack](#tech-stack)
  - [Getting Started](#getting-started)
    - [Prerequisites](#prerequisites)
    - [Installation](#installation)
    - [Development](#development)
    - [Running Tests](#running-tests)
  - [Project Structure](#project-structure)
  - [API Overview](#api-overview)
  - [Configuration](#configuration)
    - [Environment Variables](#environment-variables)
  - [Database Schema](#database-schema)
  - [Contributing](#contributing)
  - [License](#license)

## About

U-Finder Backend is an async RESTful API server built with FastAPI and Python 3.12. It powers the U-Finder platform by providing user authentication, profile management, AI-powered chat via the Dify platform, CV parsing, university programme deduplication, and an admin dashboard — all backed by PostgreSQL and Redis.

## Features

- **User Authentication** - Email/password signup & login with 6-digit email verification codes
- **Two-Factor Authentication** - TOTP-based 2FA with QR code setup, backup codes, and AES-256-GCM encrypted secret storage
- **Passkey / WebAuthn** - FIDO2-compliant passwordless authentication
- **Multi-Device Session Management** - List active sessions, selective logout, and logout-all across devices
- **User Profile Management** - JSONB-backed flexible profile with education, academic, test scores, internship, project, campus, and award sections
- **CV Upload & AI Parsing** - Upload PDF/DOCX, parse via Dify AI workflow, and return structured profile data
- **AI Chat (SSE Streaming)** - Real-time streaming chat proxy to Dify agent with user profile injection for personalised recommendations
- **Liked University Programmes** - Check, like, unlike with two-level deduplication (URL + normalised name)
- **Admin Dashboard** - JWT-based admin auth, user KPIs, LLM cost monitoring, system log preview, and user management (block/unblock/delete)
- **LLM Usage Logging** - Per-request token and cost tracking for chat and CV parsing workflows
- **Background Cleanup** - Hourly automatic cleanup of expired tokens and stale Redis sessions
- **Role-Based Access Control** - Three user types: Student (1), Institution (2), Admin (3)

## Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) 0.104 - High-performance async Python web framework
- **Server**: [Uvicorn](https://www.uvicorn.org/) 0.24 - Lightning-fast ASGI server
- **Language**: [Python](https://www.python.org/) 3.12
- **Database**: [PostgreSQL](https://www.postgresql.org/) with [asyncpg](https://github.com/MagicStack/asyncpg) 0.30 async driver
- **ORM**: [SQLAlchemy](https://www.sqlalchemy.org/) 2.0 (async mode)
- **Cache**: [Redis](https://redis.io/) 5.2 (async) - Session caching, 2FA state, WebAuthn challenges
- **AI Integration**: [Dify](https://dify.ai/) - LLM orchestration platform (chat agent + CV parsing workflow)
- **HTTP Client**: [httpx](https://www.python-httpx.org/) 0.28 - Async HTTP client for Dify API calls
- **Auth**: [bcrypt](https://github.com/pyca/bcrypt) (password hashing), [PyJWT](https://pyjwt.readthedocs.io/) (admin JWT), [pyotp](https://github.com/pyauth/pyotp) (TOTP), [webauthn](https://github.com/duo-labs/py_webauthn) 2.7 (passkeys)
- **Encryption**: [cryptography](https://cryptography.io/) - AES-256-GCM for TOTP secret encryption
- **Email**: [aiosmtplib](https://aiosmtplib.readthedocs.io/) - Async SMTP email delivery
- **Image Processing**: [Pillow](https://pillow.readthedocs.io/) + [pillow-heif](https://github.com/bigcat88/pillow_heif) - Avatar processing with HEIC/HEIF support
- **Validation**: [Pydantic](https://docs.pydantic.dev/) 2.12 + [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) - Data validation and env config
- **Testing**: [pytest](https://docs.pytest.org/) + [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) + [pytest-cov](https://github.com/pytest-dev/pytest-cov) + [httpx](https://www.python-httpx.org/) (ASGITransport)
- **CI/CD**: [GitHub Actions](https://github.com/features/actions) - Automated testing on push/PR

## Getting Started

### Prerequisites

Before you begin, ensure you have the following installed:

- **Python** (v3.12 or higher)
- **PostgreSQL** (v14 or higher)
- **Redis** (v7 or higher)
- **pip** (latest version recommended)

### Installation

1. Clone the repository (if you haven't already cloned the main U-Finder project):

```bash
git clone --recursive https://github.com/GRP-Team202511/u-finder
cd backend
```

> If you have already cloned without `--recursive`, initialise the submodules manually:
> ```bash
> git submodule update --init --recursive
> ```

2. Create and activate a virtual environment:

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Set up environment variables:

```bash
cp .env.example .env
# Edit .env with your database, Redis, Dify, and SMTP credentials
```

5. Ensure PostgreSQL and Redis are running, then initialise the database:

The database tables are created automatically on first startup via SQLAlchemy's `create_all()`.

### Development

Start the development server:

```bash
python run.py
```

The API will be available at `http://localhost:8000`. Interactive API documentation is auto-generated at:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### Running Tests

Run the full test suite with coverage:

```bash
pytest --cov=src --cov-report=term-missing
```

Run a specific test file:

```bash
pytest tests/routers/test_auth_login.py -v
```

## Project Structure

```
backend/
├── app/
│   └── main.py                  # FastAPI application entry point, lifespan, middleware
├── run.py                       # Uvicorn launcher script
├── src/
│   ├── config/
│   │   ├── settings.py          # Pydantic-settings based configuration
│   │   ├── constants.py         # UserType & TokenType enumerations
│   │   └── logger.py            # RotatingFileHandler logging setup
│   ├── database/
│   │   ├── connection.py        # Async SQLAlchemy engine & session factory
│   │   ├── redis_connection.py  # Async Redis client management
│   │   └── models.py            # ORM models (8 tables)
│   ├── routers/
│   │   ├── auth.py              # Authentication endpoints (signup, login, reset, etc.)
│   │   ├── two_factor.py        # 2FA endpoints (setup, confirm, verify, disable)
│   │   ├── passkey.py           # WebAuthn endpoints (register, login)
│   │   ├── profile.py           # Profile & avatar & liked-university endpoints
│   │   ├── chat.py              # AI chat SSE streaming & conversation management
│   │   └── admin.py             # Admin dashboard & user management
│   ├── schemas/
│   │   ├── auth.py              # Auth request/response models
│   │   ├── two_factor.py        # 2FA request/response models
│   │   ├── passkey.py           # Passkey request/response models
│   │   ├── profile.py           # Profile & university programme models
│   │   ├── chat.py              # Chat & conversation models
│   │   └── admin.py             # Admin dashboard models
│   ├── services/
│   │   ├── dify_service.py      # Dify AI API integration (chat, CV parsing, feedback)
│   │   ├── university_service.py # University programme deduplication
│   │   └── llm_usage_service.py # LLM usage & cost logging
│   ├── utils/
│   │   ├── jwt_utils.py         # JWT creation, verification, temp tokens
│   │   ├── password_utils.py    # bcrypt hashing, HMAC-SHA256 token hashing
│   │   ├── totp_utils.py        # TOTP generation, AES-GCM encryption, QR codes
│   │   ├── email_utils.py       # Async SMTP email with HTML templates
│   │   ├── session_utils.py     # Redis session CRUD (cache-aside pattern)
│   │   ├── auth_deps.py         # Shared auth dependency (get_current_user_id)
│   │   └── cleanup.py           # Expired token cleanup utilities
│   └── templates/
│       └── emails/              # HTML email templates
│           ├── verification-email.html
│           └── resetpassword-email.html
├── tests/
│   ├── conftest.py              # Test fixtures, mock DB/Redis, fake data factories
│   ├── unit/                    # Unit tests (utilities, schemas, services)
│   ├── routers/                 # Router-level tests (per endpoint)
│   │   └── utils/
│   │       └── response_asserts.py  # Reusable response schema validators
│   └── integration/             # End-to-end workflow tests
├── scripts/
│   └── test_2fa_manual.py       # Manual 2FA lifecycle test script
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions CI pipeline
├── .env.example                 # Environment variable template
├── requirements.txt             # Python dependencies
├── pytest.ini                   # pytest configuration
└── .gitignore
```

## API Overview

All endpoints are auto-documented at `/docs` (Swagger UI). Below is a summary:

| Module | Prefix | Key Endpoints |
|--------|--------|---------------|
| **Auth** | `/auth` | `POST /login`, `POST /signup`, `POST /verify`, `POST /reset`, `POST /logout`, `GET /settings/info`, `GET /settings/devices`, `DELETE /delete` |
| **2FA** | `/auth/2fa` | `POST /setup`, `POST /confirm`, `POST /verify`, `POST /disable`, `GET /status`, `POST /backup-codes/regenerate` |
| **Passkey** | `/auth/passkey` | `POST /register/options`, `POST /register/verify`, `POST /login/options`, `POST /login/verify` |
| **Profile** | `/profile` | `GET /`, `PUT /`, `GET /personal`, `PUT /personal`, `GET /array/{field}`, `PUT /array/{field}`, `POST /cv`, `GET /avatar`, `PUT /avatar`, `DELETE /avatar` |
| **Liked University** | `/profile` | `POST /liked-university/check`, `POST /liked-university/{id}`, `DELETE /liked-university/{id}`, `GET /liked-university` |
| **Chat** | `/chat` | `POST /{conversation_id}` (SSE), `POST /{task_id}/stop`, `GET /messages`, `GET /conversations`, `POST /messages/{id}/feedbacks`, `DELETE /conversations/{id}`, `POST /conversations/{id}/name` |
| **Admin** | `/api/admin` | `POST /auth/login`, `GET /dashboard/summary`, `GET /users`, `DELETE /users/{id}`, `POST /users/{id}/block`, `POST /users/{id}/unblock` |

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure the following:

```env
# Application
APP_NAME=U-Finder Backend
ENVIRONMENT=development          # development | staging | production

# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/u_finder

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Security
SECRET_KEY=your-secret-key       # Used for JWT signing and HMAC token hashing

# Dify AI
DIFY_API_BASE_URL=https://api.dify.ai/v1
DIFY_API_KEY=app-your-chat-key
DIFY_WORKFLOW_API_KEY=app-your-workflow-key

# Email (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email
SMTP_PASSWORD=your-app-password

# 2FA Encryption
TOTP_ENCRYPTION_KEY=base64-encoded-32-byte-key

# WebAuthn / Passkey
WEBAUTHN_RP_ID=localhost
WEBAUTHN_ORIGIN=http://localhost:3000
```

See [`.env.example`](.env.example) for the complete list with documentation.

## Database Schema

The backend uses 8 PostgreSQL tables:

| Table | Purpose |
|-------|---------|
| `account` | User accounts (email, password hash, user type, 2FA flags) |
| `user_profile` | JSONB-based flexible user profile (education, tests, awards, etc.) |
| `refresh_token` | Session tokens with device User-Agent tracking |
| `temp_token` | Ephemeral tokens for email verification, password reset, 2FA, account deletion |
| `totp_backup_code` | Hashed one-time backup codes for 2FA recovery |
| `passkey` | WebAuthn/FIDO2 credential storage |
| `university_program` | Deduplicated university programme entities (JSONB programme data) |
| `user_liked_university` | User ↔ liked programme association table |
| `llm_usage_log` | Per-request LLM usage records (tokens, cost, latency) |

## Contributing

Contributions are welcome! Please refer to the main repository's contributing guidelines for more information.

## License

This project is part of the U-Finder system. Please refer to the main repository for license information.
