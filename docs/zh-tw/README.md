# U-Finder 後端

![License](https://img.shields.io/badge/license-Apache%202.0-orange.svg)
![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green.svg)

🌍 [English](../../README.md) | [简体中文](../zh-cn/README.md) | **繁體中文**

U-Finder 的後端子模組，一個基於大語言模型的大學選擇輔助系統，旨在幫助學生選擇適合自己學術發展的大學。如需查看主專案，請訪問 [GRP-Team202511/u-finder](https://github.com/GRP-Team202511/u-finder)。

## 目錄

- [U-Finder 後端](#u-finder-後端)
  - [目錄](#目錄)
  - [關於](#關於)
  - [功能特性](#功能特性)
  - [技術棧](#技術棧)
  - [快速開始](#快速開始)
    - [環境要求](#環境要求)
    - [安裝](#安裝)
    - [開發](#開發)
    - [執行測試](#執行測試)
  - [專案結構](#專案結構)
  - [配置](#配置)
    - [環境變數](#環境變數)
  - [資料庫模型](#資料庫模型)
  - [貢獻](#貢獻)
  - [授權條款](#授權條款)

## 關於

U-Finder 後端是一個基於 FastAPI 和 Python 3.12 建構的非同步 RESTful API 伺服器。它為 U-Finder 平台提供使用者認證、個人資料管理、透過 Dify 平台實現的 AI 聊天、履歷解析、大學項目去重以及管理員儀表板等功能，底層由 PostgreSQL 和 Redis 驅動。

## 功能特性

- **使用者認證** - 支援電子郵件/密碼註冊與登入，6 位數電子郵件驗證碼
- **雙因素認證 (2FA)** - 基於 TOTP 的雙因素認證，支援 QR Code 設定、備份碼和 AES-256-GCM 加密金鑰儲存
- **Passkey / WebAuthn** - 符合 FIDO2 標準的免密認證
- **多裝置工作階段管理** - 查看活躍工作階段、選擇性登出和全裝置登出
- **使用者資料管理** - 基於 JSONB 的彈性使用者資料，涵蓋教育背景、學術成果、考試成績、實習、專案、校園經歷和獲獎情況
- **履歷上傳與 AI 解析** - 上傳 PDF/DOCX，透過 Dify AI 工作流程解析並回傳結構化資料
- **AI 聊天 (SSE 串流傳輸)** - 即時串流聊天代理，注入使用者資料以提供個人化大學推薦
- **收藏大學項目** - 查看、收藏、取消收藏，支援兩級去重（URL + 標準化名稱）
- **管理員儀表板** - 基於 JWT 的管理員認證（含超級管理員角色）、使用者 KPI、LLM 成本監控（阿里雲和騰訊雲計費）、系統日誌預覽（支援分頁）和使用者管理（封鎖/解除封鎖/刪除）
- **LLM 用量記錄** - 按請求記錄 Token 和成本，涵蓋聊天與履歷解析工作流程
- **背景清理** - 每小時自動清理過期權杖和失效 Redis 工作階段
- **反機器人保護** - 整合 Cloudflare Turnstile，保護註冊、登入和密碼重設端點
- **雲服務計費監控** - 阿里雲和騰訊雲 API 費用追蹤，用於管理員儀表板
- **基於角色的存取控制** - 四種使用者類型：學生 (1)、機構 (2)、管理員 (3)、超級管理員 (4)

## 技術棧

- **框架**: [FastAPI](https://fastapi.tiangolo.com/) 0.104 - 高效能非同步 Python Web 框架
- **伺服器**: [Uvicorn](https://www.uvicorn.org/) 0.24 - 高效能 ASGI 伺服器
- **語言**: [Python](https://www.python.org/) 3.12
- **資料庫**: [PostgreSQL](https://www.postgresql.org/) + [asyncpg](https://github.com/MagicStack/asyncpg) 0.30 非同步驅動
- **ORM**: [SQLAlchemy](https://www.sqlalchemy.org/) 2.0（非同步模式）
- **快取**: [Redis](https://redis.io/) 5.2（非同步） - 工作階段快取、2FA 狀態、WebAuthn 挑戰
- **AI 整合**: [Dify](https://dify.ai/) - LLM 編排平台（聊天 Agent + 履歷解析工作流程）
- **HTTP 客戶端**: [httpx](https://www.python-httpx.org/) 0.28 - 非同步 HTTP 客戶端，用於 Dify API 呼叫
- **認證**: [bcrypt](https://github.com/pyca/bcrypt)（密碼雜湊）、[PyJWT](https://pyjwt.readthedocs.io/)（管理員 JWT）、[pyotp](https://github.com/pyauth/pyotp)（TOTP）、[webauthn](https://github.com/duo-labs/py_webauthn) 2.7（Passkey）
- **加密**: [cryptography](https://cryptography.io/) - 用於 TOTP 金鑰的 AES-256-GCM 加密
- **電子郵件**: [aiosmtplib](https://aiosmtplib.readthedocs.io/) - 非同步 SMTP 電子郵件傳送
- **影像處理**: [Pillow](https://pillow.readthedocs.io/) + [pillow-heif](https://github.com/bigcat88/pillow_heif) - 頭像處理，支援 HEIC/HEIF 格式
- **資料驗證**: [Pydantic](https://docs.pydantic.dev/) 2.12 + [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) - 資料驗證與環境配置
- **測試**: [pytest](https://docs.pytest.org/) + [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) + [pytest-cov](https://github.com/pytest-dev/pytest-cov) + [httpx](https://www.python-httpx.org/)（ASGITransport）
- **CI/CD**: [GitHub Actions](https://github.com/features/actions) - 推送/PR 時自動執行測試，CD 測試環境與正式環境部署
- **容器化**: [Docker](https://www.docker.com/) + [Docker Compose](https://docs.docker.com/compose/) - 容器化部署，包含 PostgreSQL 和 Redis
- **反機器人**: [Cloudflare Turnstile](https://www.cloudflare.com/products/turnstile/) - 認證端點的機器人防護

## 快速開始

### 環境要求

在開始之前，請確保已安裝以下軟體：

- **Python**（v3.12 或更高版本）
- **pip**（建議使用最新版本）
- **Docker** 與 **Docker Compose** - 用於執行 PostgreSQL 和 Redis。請在 U-Finder 主儲存庫的 [`database/`](https://github.com/GRP-Team202511/u-finder/tree/main/database) 目錄下執行 `docker compose up -d` 啟動。

### 安裝

1. 複製儲存庫（如果尚未複製主 U-Finder 專案）：

```bash
git clone --recursive https://github.com/GRP-Team202511/u-finder
cd u-finder/backend
```

> 如果複製時未使用 `--recursive`，請手動初始化子模組：
> ```bash
> git submodule update --init --recursive
> ```

2. 建立並啟用虛擬環境：

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

3. 安裝相依套件：

```bash
pip install -r requirements.txt
```

4. 配置環境變數：

```bash
cp .env.example .env
# 編輯 .env，填入資料庫、Redis、Dify 和 SMTP 憑證
```

5. 透過 Docker Compose 啟動 PostgreSQL 和 Redis（在 U-Finder 主儲存庫的 `database/` 目錄下執行）：

```bash
cd ../database
docker compose up -d
cd ../backend
```

資料庫表會在首次啟動時透過 SQLAlchemy 的 `create_all()` 自動建立。

### 開發

啟動開發伺服器：

```bash
python run.py
```

API 將在 `http://localhost:8000` 上可用。完整 API 文件請參閱 [Apifox](https://bop63bqzti.apifox.cn)。

### 執行測試

執行完整測試套件（含覆蓋率）：

```bash
pytest --cov=src --cov-report=term-missing
```

執行指定測試檔案：

```bash
pytest tests/routers/test_auth_login.py -v
```

## 專案結構

```
backend/
├── app/
│   └── main.py                  # FastAPI 應用程式入口，生命週期管理，中介軟體
├── run.py                       # Uvicorn 啟動腳本
├── src/
│   ├── config/
│   │   ├── settings.py          # 基於 Pydantic-settings 的配置管理
│   │   ├── constants.py         # UserType 與 TokenType 列舉
│   │   └── logger.py            # RotatingFileHandler 日誌配置
│   ├── database/
│   │   ├── connection.py        # 非同步 SQLAlchemy 引擎與工作階段工廠
│   │   ├── redis_connection.py  # 非同步 Redis 客戶端管理
│   │   └── models.py            # ORM 模型（9 張表）
│   ├── routers/
│   │   ├── auth.py              # 認證端點（註冊、登入、重設等）
│   │   ├── two_factor.py        # 2FA 端點（設定、確認、驗證、停用）
│   │   ├── passkey.py           # WebAuthn 端點（註冊、登入）
│   │   ├── profile.py           # 個人資料、頭像與收藏大學端點
│   │   ├── chat.py              # AI 聊天 SSE 串流傳輸與對話管理
│   │   └── admin.py             # 管理員儀表板與使用者管理
│   ├── schemas/
│   │   ├── auth.py              # 認證請求/回應模型
│   │   ├── two_factor.py        # 2FA 請求/回應模型
│   │   ├── passkey.py           # Passkey 請求/回應模型
│   │   ├── profile.py           # 個人資料與大學項目模型
│   │   ├── chat.py              # 聊天與對話模型
│   │   └── admin.py             # 管理員儀表板模型
│   ├── services/
│   │   ├── dify_service.py      # Dify AI API 整合（聊天、履歷解析、回饋）
│   │   ├── university_service.py # 大學項目去重
│   │   ├── llm_usage_service.py # LLM 用量與成本記錄
│   │   ├── aliyun_billing_service.py  # 阿里雲計費 API
│   │   └── tencent_billing_service.py # 騰訊雲計費 API
│   ├── utils/
│   │   ├── jwt_utils.py         # JWT 建立、驗證、臨時權杖
│   │   ├── password_utils.py    # bcrypt 雜湊、HMAC-SHA256 權杖雜湊
│   │   ├── totp_utils.py        # TOTP 產生、AES-GCM 加密、QR Code
│   │   ├── email_utils.py       # 非同步 SMTP 電子郵件與 HTML 範本
│   │   ├── session_utils.py     # Redis 工作階段 CRUD（Cache-Aside 模式）
│   │   ├── auth_deps.py         # 共用認證相依性（get_current_user_id）
│   │   ├── cleanup.py           # 過期權杖清理工具
│   │   └── turnstile.py         # Cloudflare Turnstile 驗證
│   └── templates/
│       └── emails/              # HTML 電子郵件範本
│           ├── verification-email.html
│           ├── resetpassword-email.html
│           └── delete-account-email.html
├── tests/
│   ├── conftest.py              # 測試固定裝置、Mock DB/Redis、假資料工廠
│   ├── unit/                    # 單元測試（工具類、Schema、服務）
│   ├── routers/                 # 路由級測試（按端點劃分）
│   │   └── utils/
│   │       └── response_asserts.py  # 可重複使用回應 Schema 驗證器
│   └── integration/             # 端到端工作流程測試
├── scripts/
│   └── test_2fa_manual.py       # 手動 2FA 生命週期測試腳本
├── docker/
│   └── db/
│       └── init.sql             # PostgreSQL 架構初始化
├── .github/
│   └── workflows/
│       ├── ci.yml               # GitHub Actions CI 流水線
│       ├── cd-staging.yml       # CD 測試環境部署
│       ├── cd-production.yml    # CD 正式環境部署
│       └── docker-build.yml     # Docker 映像建置工作流
├── Dockerfile                   # 正式環境 Docker 映像
├── docker-compose.yml           # 本地開發服務
├── docker-compose.prod.yml      # 正式環境 Docker Compose
├── .env.example                 # 環境變數範本
├── requirements.txt             # Python 相依套件
├── pytest.ini                   # pytest 配置
└── .gitignore
```

## 配置

### 環境變數

將 `.env.example` 複製為 `.env` 並配置以下內容：

```env
# 應用程式
APP_NAME=U-Finder Backend
ENVIRONMENT=development          # development | staging | production

# 伺服器
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# 資料庫
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/u_finder

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# 安全性
SECRET_KEY=your-secret-key       # 用於 JWT 簽章和 HMAC 權杖雜湊

# Dify AI
DIFY_API_BASE_URL=https://api.dify.ai/v1
DIFY_API_KEY=app-your-chat-key
DIFY_WORKFLOW_API_KEY=app-your-workflow-key

# 電子郵件 (SMTP)
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

完整變數列表及說明請參見 [`.env.example`](../../.env.example)。

## 資料庫模型

後端使用 9 張 PostgreSQL 表：

| 表名 | 用途 |
|------|------|
| `account` | 使用者帳戶（電子郵件、密碼雜湊、使用者類型、2FA 旗標） |
| `user_profile` | 基於 JSONB 的彈性使用者資料（教育、考試、獲獎等） |
| `refresh_token` | 工作階段權杖，附帶裝置 User-Agent 追蹤 |
| `temp_token` | 臨時權杖，用於電子郵件驗證、密碼重設、2FA、帳戶刪除 |
| `totp_backup_code` | 經雜湊處理的一次性備份碼，用於 2FA 復原 |
| `passkey` | WebAuthn/FIDO2 憑證儲存 |
| `university_program` | 去重後的大學項目實體（JSONB 項目資料） |
| `user_liked_university` | 使用者 ↔ 收藏項目關聯表 |
| `llm_usage_log` | 按請求記錄的 LLM 用量（Token、成本、延遲） |

## 貢獻

歡迎貢獻！更多資訊請參閱主儲存庫的貢獻指南。

## 授權條款

本專案是 U-Finder 系統的一部分，授權條款資訊請參閱主儲存庫。
