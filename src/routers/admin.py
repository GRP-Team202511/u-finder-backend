"""
Admin router module.

Endpoints implemented:
- POST /api/admin/auth/login
- GET  /api/admin/dashboard/summary
"""
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.constants import UserType
from src.config.logger import get_logger
from src.database import get_db, Account
from src.database.models import LlmUsageLog
from src.schemas.admin import (
    AdminDashboardSummary,
    AdminLoginRequest,
    AdminLoginResponse,
    AdminUser,
    LlmCostToday,
    LogEntry,
    ModelCostSnapshot,
    Money,
)
from src.utils.jwt_utils import create_access_token, verify_token
from src.utils.password_utils import verify_password

logger = get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])

# Log directory (same as src/config/logger.py)
LOG_DIR = Path("logs")

# Regex for parsing a single log line produced by our RotatingFileHandler.
# Format: "2026-03-10 17:34:32 - name - LEVEL - [file:line] - message"
_LOG_LINE_RE = re.compile(
    r"^(?P<datetime>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r" - [^ ]+ - "
    r"(?P<level>[A-Z]+)"
    r" - \[[^\]]+\] - "
    r"(?P<message>.+)$"
)


# ── Helper: require admin JWT ────────────────────────────────────────

async def require_admin(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Account:
    """
    Dependency that validates a JWT Bearer token and ensures the caller
    is an admin (user_type == 3) who is not blocked.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )

    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )

    result = await db.execute(
        select(Account).where(Account.user_id == int(user_id))
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid or expired token"},
        )

    if account.is_blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Account is blocked"},
        )

    if account.user_type != UserType.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Admin permission required"},
        )

    return account


# ── POST /api/admin/auth/login ───────────────────────────────────────

@router.post(
    "/auth/login",
    response_model=AdminLoginResponse,
    responses={
        401: {"description": "Invalid email or password"},
        403: {"description": "Account blocked or not admin"},
    },
)
async def admin_login(
    body: AdminLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate admin user and return a JWT access token."""
    email = body.email.lower()
    logger.info("Admin login attempt: %s", email)

    # 1. Find account by email
    result = await db.execute(
        select(Account).where(Account.email == email)
    )
    account = result.scalar_one_or_none()

    if not account or not verify_password(body.password, account.password_hashed):
        logger.warning("Admin login failed: invalid credentials for %s", email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid email or password"},
        )

    # 2. Must be admin
    if account.user_type != UserType.ADMIN:
        logger.warning("Admin login rejected: user_type=%s for %s", account.user_type, email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Admin permission required"},
        )

    # 3. Must not be blocked
    if account.is_blocked:
        logger.warning("Admin login rejected: blocked account %s", email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Account is blocked"},
        )

    # 4. Issue JWT (payload includes user_id + user_type)
    token = create_access_token(
        data={
            "sub": str(account.user_id),
            "email": account.email,
            "user_type": account.user_type,
        }
    )

    logger.info("Admin login successful: user_id=%s", account.user_id)
    return AdminLoginResponse(
        id=account.user_id,
        name=account.user_name,
        token=token,
    )


# ── GET /api/admin/dashboard/summary ─────────────────────────────────

@router.get(
    "/dashboard/summary",
    response_model=AdminDashboardSummary,
)
async def get_dashboard_summary(
    logs_date: Optional[str] = Query(None, description="Date for logs preview (YYYY-MM-DD), defaults to today"),
    logs_level: Optional[str] = Query("all", regex="^(all|info|warn|error)$"),
    cost_model: Optional[str] = Query("chat", regex="^(chat|cv_parsing)$"),
    cost_time_range: Optional[str] = Query("last_24h", regex="^(last_24h|last_7d|last_1m)$"),
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the all-in-one dashboard payload."""
    now = datetime.now(timezone.utc)
    today = now.date()

    # Parse logs_date: treat None or empty string as today
    if logs_date:
        try:
            parsed_logs_date = date.fromisoformat(logs_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Invalid date format, expected YYYY-MM-DD"},
            )
    else:
        parsed_logs_date = today

    # ── KPI: total_users ────────────────────────────────────────────────
    total_users = (await db.execute(select(func.count(Account.user_id)))).scalar() or 0

    # ── KPI: total_users_delta_week ─────────────────────────────────────
    week_ago = now - timedelta(days=7)
    total_users_delta_week = (
        await db.execute(
            select(func.count(Account.user_id)).where(Account.created_at >= week_ago)
        )
    ).scalar() or 0

    # ── KPI: llm_cost_today ─────────────────────────────────────────────
    llm_cost_today = await _get_llm_cost_today(db, today)

    # ── Recent Users (3 newest) ─────────────────────────────────────────
    recent_users = await _get_recent_users(db, limit=3)

    # ── System Logs Preview ─────────────────────────────────────────────
    recent_logs = _get_logs_preview(parsed_logs_date, logs_level or "all")

    # ── Model Cost Snapshot ─────────────────────────────────────────────
    model_cost_snapshot = await _get_model_cost_snapshot(
        db, cost_model or "chat", cost_time_range or "last_24h", now,
    )

    return AdminDashboardSummary(
        total_users=total_users,
        total_users_delta_week=total_users_delta_week,
        llm_cost_today=llm_cost_today,
        recent_users=recent_users,
        recent_logs=recent_logs,
        model_cost_snapshot=model_cost_snapshot,
    )


# ── Private helpers ──────────────────────────────────────────────────

async def _get_llm_cost_today(db: AsyncSession, today: date) -> LlmCostToday:
    """SUM(total_price) from llm_usage_log where created_at::date = today."""
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    result = await db.execute(
        select(func.sum(func.cast(LlmUsageLog.total_price, func.numeric())))
        .where(LlmUsageLog.created_at >= start, LlmUsageLog.created_at < end)
    )
    raw = result.scalar()
    amount = float(raw) if raw else 0.0

    return LlmCostToday(currency="USD", amount=round(amount, 4), budget_per_day=None)


async def _get_recent_users(db: AsyncSession, limit: int = 3) -> List[AdminUser]:
    """Return the N most recently created accounts."""
    result = await db.execute(
        select(Account).order_by(Account.created_at.desc()).limit(limit)
    )
    accounts = result.scalars().all()

    users: List[AdminUser] = []
    for acc in accounts:
        user_status = _map_status(acc)
        actions = _available_actions(user_status)
        users.append(
            AdminUser(
                id=acc.user_id,
                name=acc.user_name,
                email=acc.email,
                type=str(acc.user_type),
                status=user_status,
                created_at=acc.created_at,
                available_actions=actions,
            )
        )
    return users


def _map_status(account: Account) -> str:
    """Derive display status from account flags."""
    if account.is_blocked:
        return "blocked"
    if not account.email_verified:
        return "pending"
    return "active"


def _available_actions(user_status: str) -> List[str]:
    """Return available moderation actions based on current status."""
    if user_status == "blocked":
        return ["unblock", "delete"]
    return ["block", "delete"]


# ── Logs helpers ─────────────────────────────────────────────────────

def _get_logs_preview(
    target_date: date,
    level: str,
) -> List[LogEntry]:
    """
    Read log entries from the on-disk log file for the given date and
    level filter.  Returns up to 5 most recent entries.
    """
    # Parse log entries
    entries = _parse_log_file(target_date, level)

    # Take the 5 most recent, returned in time DESC order (newest first)
    return list(reversed(entries[-5:])) if len(entries) > 5 else list(reversed(entries))


def _parse_log_file(target_date: date, level: str) -> List[LogEntry]:
    """Parse a single day's log file and return matching entries."""
    log_file = LOG_DIR / f"app_{target_date.strftime('%Y%m%d')}.log"
    if not log_file.exists():
        return []

    # Normalise Python log levels to our API levels
    level_map = {
        "DEBUG": "info",
        "INFO": "info",
        "WARNING": "warn",
        "ERROR": "error",
        "CRITICAL": "error",
    }

    entries: List[LogEntry] = []
    try:
        with open(log_file, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                m = _LOG_LINE_RE.match(raw_line.strip())
                if not m:
                    continue
                normalised = level_map.get(m.group("level"), "info")

                # Apply level filter
                if level != "all" and normalised != level:
                    continue

                ts = datetime.strptime(m.group("datetime"), "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                entries.append(
                    LogEntry(time=ts, level=normalised, message=m.group("message"))
                )
    except OSError:
        logger.warning("Failed to read log file: %s", log_file)

    return entries


# ── Model Cost helpers ───────────────────────────────────────────────

def _time_range_to_since(time_range: str, now: datetime) -> datetime:
    """Convert a time_range enum value to a UTC datetime lower-bound."""
    delta_map = {
        "last_24h": timedelta(hours=24),
        "last_7d": timedelta(days=7),
        "last_1m": timedelta(days=30),
    }
    return now - delta_map.get(time_range, timedelta(hours=24))


async def _get_model_cost_snapshot(
    db: AsyncSession,
    model: str,
    time_range: str,
    now: datetime,
) -> ModelCostSnapshot:
    """Aggregate llm_usage_log for the specified model + time window."""
    since = _time_range_to_since(time_range, now)

    base_filter = [
        LlmUsageLog.source == model,
        LlmUsageLog.created_at >= since,
    ]

    # total_requests
    total_requests = (
        await db.execute(select(func.count(LlmUsageLog.id)).where(*base_filter))
    ).scalar() or 0

    # avg_latency_seconds — latency_seconds is stored as String, cast to float
    avg_latency_raw = (
        await db.execute(
            select(func.avg(func.cast(LlmUsageLog.latency_seconds, func.numeric())))
            .where(*base_filter)
        )
    ).scalar()
    avg_latency = round(float(avg_latency_raw), 2) if avg_latency_raw else None

    # tokens_total
    tokens_total = (
        await db.execute(
            select(func.sum(LlmUsageLog.total_tokens)).where(*base_filter)
        )
    ).scalar() or 0

    # estimated_cost — total_price is stored as String, cast to numeric
    cost_raw = (
        await db.execute(
            select(func.sum(func.cast(LlmUsageLog.total_price, func.numeric())))
            .where(*base_filter)
        )
    ).scalar()
    cost_amount = round(float(cost_raw), 4) if cost_raw else 0.0

    return ModelCostSnapshot(
        total_requests=total_requests,
        avg_latency_seconds=avg_latency,
        tokens_total=tokens_total,
        estimated_cost=Money(currency="USD", amount=cost_amount),
    )
