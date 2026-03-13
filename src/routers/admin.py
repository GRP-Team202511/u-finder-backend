"""
Admin router module.

Endpoints implemented:
- POST   /api/admin/auth/login
- GET    /api/admin/dashboard/summary
- GET    /api/admin/users
- DELETE /api/admin/users/{user_id}
- POST   /api/admin/users/{user_id}/block
- POST   /api/admin/users/{user_id}/unblock
"""
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import Numeric, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.constants import UserType
from src.config.logger import get_logger
from src.database import get_db, Account
from src.database.models import LlmUsageLog
from src.schemas.admin import (
    ActionResult,
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


# ── GET /api/admin/users ──────────────────────────────────────────────

@router.get(
    "/users",
    response_model=List[AdminUser],
    responses={
        401: {"description": "Missing, malformed, or expired Bearer token"},
        403: {"description": "Valid token but user is not admin"},
        422: {"description": "Missing or invalid Authorization header"},
    },
    summary="List users",
)
async def list_users(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Returns a list of all user accounts for admin management."""
    try:
        result = await db.execute(select(Account).order_by(Account.user_id))
        accounts = result.scalars().all()

        users = []
        for acc in accounts:
            user_status = _map_status(acc)
            users.append(
                AdminUser(
                    id=acc.user_id,
                    name=acc.user_name,
                    email=acc.email,
                    type=str(acc.user_type),
                    status=user_status,
                    created_at=acc.created_at,
                    available_actions=_available_actions(user_status),
                )
            )

        return users

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error listing users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ── DELETE /api/admin/users/{user_id} ─────────────────────────────────

@router.delete(
    "/users/{userId}",
    response_model=ActionResult,
    responses={
        401: {"description": "Missing, malformed, or expired Bearer token"},
        403: {"description": "Valid token but user is not admin, or attempting self-deletion"},
        404: {"description": "Requested resource does not exist"},
        422: {"description": "Missing or invalid Authorization header"},
    },
    summary="Delete user",
)
async def delete_user(
    userId: int,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a user account and all associated data."""
    # Prevent self-deletion
    if userId == admin.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Cannot delete your own account"},
        )

    try:
        result = await db.execute(
            select(Account).where(Account.user_id == userId)
        )
        account = result.scalar_one_or_none()

        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "User not found"},
            )

        # Delete account (cascades to profile, refresh_tokens, etc.)
        await db.delete(account)
        await db.commit()

        # Delete avatar files from disk (after DB commit succeeds)
        _cleanup_avatar_files(userId)

        logger.info("Admin %s deleted user %s", admin.user_id, userId)
        return ActionResult(result="success")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("Error deleting user %s", userId)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ── POST /api/admin/users/{user_id}/block ─────────────────────────────

@router.post(
    "/users/{userId}/block",
    response_model=ActionResult,
    responses={
        401: {"description": "Missing, malformed, or expired Bearer token"},
        403: {"description": "Not admin, or target is an admin account"},
        404: {"description": "Requested resource does not exist"},
    },
    summary="Block user",
)
async def block_user(
    userId: int,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Sets account.is_blocked = true. Idempotent."""
    target = await _get_target_non_admin(userId, db)

    target.is_blocked = True
    await db.commit()

    logger.info("Admin %s blocked user %s", admin.user_id, userId)
    return ActionResult(result="success")


# ── POST /api/admin/users/{user_id}/unblock ───────────────────────────

@router.post(
    "/users/{userId}/unblock",
    response_model=ActionResult,
    responses={
        401: {"description": "Missing, malformed, or expired Bearer token"},
        403: {"description": "Not admin, or target is an admin account"},
        404: {"description": "Requested resource does not exist"},
    },
    summary="Unblock user",
)
async def unblock_user(
    userId: int,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Sets account.is_blocked = false. Idempotent."""
    target = await _get_target_non_admin(userId, db)

    target.is_blocked = False
    await db.commit()

    logger.info("Admin %s unblocked user %s", admin.user_id, userId)
    return ActionResult(result="success")


# ── Private helpers ──────────────────────────────────────────────────

async def _get_target_non_admin(user_id: int, db: AsyncSession) -> Account:
    """
    Fetch a user by ID; raise 404 if not found, 403 if the target is an
    admin account.  Shared by block / unblock endpoints.
    """
    result = await db.execute(
        select(Account).where(Account.user_id == user_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"},
        )

    if account.user_type == UserType.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Cannot block/unblock an admin account"},
        )

    return account


def _cleanup_avatar_files(user_id: int) -> None:
    """Remove the user's avatar directory from disk, if it exists."""
    avatar_dir = Path("uploads") / "avatars" / str(user_id)
    if avatar_dir.is_dir():
        shutil.rmtree(avatar_dir, ignore_errors=True)

async def _get_llm_cost_today(db: AsyncSession, today: date) -> LlmCostToday:
    """SUM(total_price) from llm_usage_log where created_at::date = today."""
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    result = await db.execute(
        select(func.sum(func.cast(LlmUsageLog.total_price, Numeric)))
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
    level filter.  Returns up to 5 most recent entries (newest first).
    """
    entries = _parse_log_file(target_date, level, limit=5)
    return entries


def _parse_log_file(target_date: date, level: str, *, limit: int = 5) -> List[LogEntry]:
    """
    Parse a single day's log file and return up to *limit* most recent
    matching entries in newest-first order.

    Reads from the end of the file to avoid scanning potentially large
    logs when only a handful of recent entries are needed.
    """
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
            lines = fh.readlines()

        # Iterate from the end so we can stop early once we have enough
        for raw_line in reversed(lines):
            if len(entries) >= limit:
                break

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

    # entries were collected newest-first; return in that order
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
            select(func.avg(func.cast(LlmUsageLog.latency_seconds, Numeric)))
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
            select(func.sum(func.cast(LlmUsageLog.total_price, Numeric)))
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
