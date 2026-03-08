"""
Global pytest configuration and fixtures.
- Uses a standalone test app (no real DB/Redis connections triggered)
- Injects mock DB and mock Redis via FastAPI dependency_overrides
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from httpx import AsyncClient, ASGITransport

from src.routers import auth_router, profile_router, chat_router, two_factor_router
from src.database.connection import get_db
from src.database.redis_connection import get_redis


# ──────────────────────────────────────────────
# Standalone test app (avoids main.py lifespan connecting to real DB/Redis)
# ──────────────────────────────────────────────
def build_test_app() -> FastAPI:
    app = FastAPI()

    # Mirror the custom exception handler from app/main.py so that
    # HTTPException(detail={"message": "..."}) returns {"message": "..."}
    # instead of the default {"detail": {"message": "..."}}.
    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, exc: HTTPException):
        content = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=getattr(exc, "headers", None),
        )

    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(chat_router)
    app.include_router(two_factor_router)
    return app


# ──────────────────────────────────────────────
# Mock DB Session Fixture
# ──────────────────────────────────────────────
@pytest.fixture
def mock_db():
    """
    Returns an AsyncMock simulating an AsyncSession.

    Default behaviour:
    - execute() result's .scalar_one_or_none() returns None
    - commit(), delete(), refresh() complete without raising

    Override in individual tests:
        mock_db.execute.return_value.scalar_one_or_none.return_value = fake_user
    """
    session = AsyncMock()

    # Default: execute() result's scalar_one_or_none() returns None
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = None
    session.execute.return_value = execute_result

    # session.add() is synchronous in SQLAlchemy — use MagicMock to avoid
    # "coroutine never awaited" warnings when the router calls db.add(...)
    session.add = MagicMock()

    return session


# ──────────────────────────────────────────────
# Mock Redis Fixture
# ──────────────────────────────────────────────
@pytest.fixture
def mock_redis():
    """
    Returns an AsyncMock simulating a Redis client.

    Default behaviour:
    - get() returns None (cache miss)
    - hgetall() returns {} (no session / cache miss)
    - set(), delete() complete without raising
    """
    redis = AsyncMock()
    redis.get.return_value = None
    redis.hgetall.return_value = {}
    return redis


# ──────────────────────────────────────────────
# HTTP Test Client Fixture
# ──────────────────────────────────────────────
@pytest.fixture
async def client(mock_db, mock_redis):
    """
    Returns an httpx.AsyncClient with mock DB and mock Redis injected.

    Usage example:
        async def test_something(client, mock_db):
            mock_db.execute.return_value.scalar_one_or_none.return_value = fake_user
            response = await client.post("/auth/login", json={...})
            assert response.status_code == 200
    """
    app = build_test_app()

    async def override_get_db():
        yield mock_db

    async def override_get_redis():
        yield mock_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ──────────────────────────────────────────────
# Fake Data Factories
# ──────────────────────────────────────────────
@pytest.fixture
def fake_account():
    """Returns a mock Account ORM object."""
    account = MagicMock()
    account.user_id = 1
    account.user_name = "Test User"
    account.email = "test@example.com"
    account.password_hashed = "$2b$12$placeholder_hashed_password"
    account.user_type = 1
    account.is_blocked = False
    account.is_2fa_enabled = False
    account.passkey_enabled = False
    account.created_at = MagicMock()
    account.created_at.isoformat.return_value = "2026-01-01T00:00:00+00:00"
    account.updated_at = MagicMock()
    account.updated_at.isoformat.return_value = "2026-01-01T00:00:00+00:00"
    return account


@pytest.fixture
def fake_temp_token():
    """Returns a mock TempToken ORM object (default type: email_verify)."""
    from datetime import datetime, timedelta, timezone

    token = MagicMock()
    token.id = 1
    token.user_id = 1
    token.token_hashed = "fake-temp-token-value"
    token.token_type = "email_verify"
    token.verification_code_hashed = "$2b$12$placeholder_code_hash"
    token.expire_at = datetime.now(timezone.utc) + timedelta(hours=24)
    token.created_at = datetime.now(timezone.utc) - timedelta(seconds=120)  # created 2 minutes ago
    return token


@pytest.fixture
def fake_refresh_token():
    """Returns a mock RefreshToken ORM object."""
    from datetime import datetime, timedelta, timezone

    rt = MagicMock()
    rt.id = 1
    rt.user_id = 1
    rt.token_hashed = "fake-hashed-refresh-token"
    rt.user_agent = "pytest"
    rt.expire_at = datetime.now(timezone.utc) + timedelta(days=30)
    return rt


# ──────────────────────────────────────────────
# Profile Fixtures
# ──────────────────────────────────────────────

FAKE_BEARER_TOKEN = "fake-profile-test-token"


@pytest.fixture
def auth_headers():
    """
    Returns Authorization header dict carrying a fixed Bearer token.

    For profile endpoint tests that need successful authentication,
    configure mock_redis so that hgetall returns a valid session:

        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

    For tests verifying 401 behaviour, leave mock_redis at its default
    (hgetall returns {}) and mock_db returning None — _get_current_user_id
    will then raise HTTP 401.
    """
    return {"Authorization": f"Bearer {FAKE_BEARER_TOKEN}"}


@pytest.fixture
def fake_profile():
    """
    Returns a mock UserProfile ORM object with realistic data.

    Fields that mirror the database model columns:
      - user_id, basic_info
      - education, academic, test, internship, project, campus, award
    """
    profile = MagicMock()
    profile.user_id = 1
    profile.basic_info = {
        "name": "Test User",
        "gender": "male",
        "birthday": "2002-07-15",
    }
    profile.education = [
        {
            "type": "undergraduate",
            "name": "Test University",
            "major": "Computer Science",
        }
    ]
    profile.academic = [
        {
            "type": "research paper",
            "title": "Sample Paper Title",
        }
    ]
    profile.test = [
        {
            "type": "IELTS",
            "test_date": "2023-10-21",
            "scores": {"overall": "7.5"},
        }
    ]
    profile.internship = [
        {
            "company": "Test Corp",
            "role": "Software Engineer Intern",
        }
    ]
    profile.project = [
        {
            "name": "Sample Project",
            "role": "Backend Developer",
        }
    ]
    profile.campus = [
        {
            "name": "Test Society",
            "description": "Sample campus activity.",
        }
    ]
    profile.award = [
        {
            "name": "Merit Scholarship",
            "description": "Awarded for academic performance.",
        }
    ]
    return profile


# ──────────────────────────────────────────────
# Liked University Fixtures
# ──────────────────────────────────────────────

SAMPLE_PROGRAM_CARD = {
    "university": {
        "name": "Massachusetts Institute of Technology",
        "country": "United States",
        "city": "Cambridge",
        "official_website": "https://www.mit.edu",
    },
    "faculty": {
        "name": "School of Engineering",
        "official_website": "https://engineering.mit.edu",
    },
    "degree_program": {
        "name": "Master of Science in Computer Science",
        "degree_level": "Master",
        "field": "Computer Science",
        "track_or_specialization": "Artificial Intelligence",
        "program_type": "Full-time",
        "duration": "2 years",
        "language": "English",
    },
    "admissions": {
        "academic_requirements": "Bachelor's degree in CS or related field, GPA 3.5+",
        "language_requirements": "TOEFL 100+ or IELTS 7.0+",
        "other_requirements": "GRE recommended",
        "application_deadline": "December 15, 2026",
    },
    "tuition": {
        "amount": 57590,
        "currency": "USD",
        "per": "year",
    },
    "career_outcomes": ["Software Engineer", "ML Engineer"],
    "official_program_url": "https://www.eecs.mit.edu/academics/graduate-programs/ms-program/",
    "last_verified": "2026-03-01",
}


@pytest.fixture
def sample_program_card():
    """Returns a realistic LLM program card dict (request body for /check)."""
    return SAMPLE_PROGRAM_CARD.copy()


@pytest.fixture
def fake_university_program():
    """Returns a mock UniversityProgram ORM object."""
    from datetime import datetime, timezone
    program = MagicMock()
    program.id = "550e8400-e29b-41d4-a716-446655440000"
    program.normalized_url = "eecs.mit.edu/academics/graduate-programs/ms-program"
    program.normalized_name = "massachusetts institute of technology | master of science in computer science | master"
    program.program_data = SAMPLE_PROGRAM_CARD.copy()
    program.created_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    program.updated_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    return program


@pytest.fixture
def fake_liked_record():
    """Returns a mock UserLikedUniversity ORM object."""
    from datetime import datetime, timezone
    record = MagicMock()
    record.id = 1
    record.user_id = 1
    record.university_program_id = "550e8400-e29b-41d4-a716-446655440000"
    record.created_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    return record
