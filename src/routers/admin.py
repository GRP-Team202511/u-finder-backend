"""
Admin router module.

Endpoints implemented:
- POST   /api/admin/auth/login
- GET    /api/admin/dashboard/summary
- GET    /api/admin/users
- DELETE /api/admin/users/{user_id}
- POST   /api/admin/users/{userId}/block
- POST   /api/admin/users/{userId}/unblock
- PATCH  /api/admin/users/{userId}/role
"""
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import Numeric, func, select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from user_agents import parse as parse_ua

from src.config.constants import UserType, TokenType
from src.config.logger import get_logger
from src.database import get_db, get_redis, Account, TotpBackupCode, RefreshToken, TempToken
from src.database.models import LlmUsageLog
from src.utils.auth_deps import get_current_user_id
from src.utils.session_utils import delete_session_by_hash
from src.utils import generate_verification_code, send_verification_email, decrypt_secret, verify_totp_code, check_totp_replay, generate_backup_codes, create_temp_token
from src.utils.password_utils import hash_token
from src.schemas.admin import (
    ActionResult,
    AdminDashboardSummary,
    AdminLoginRequest,
    AdminLoginResponse,
    AdminUser,
    ChangeRoleRequest,
    LlmCostToday,
    LogEntry,
    ModelCostSnapshot,
    Money,
)
from src.schemas.auth import (
    GetUserInfoResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyResetCodeRequest,
    VerifyResetCodeResponse,
    ResendResetCodeResponse,
    ConfirmResetPasswordRequest,
    ConfirmResetPasswordResponse,
    DeviceSession,
    DevicesResponse,
    LogoutDeviceResponse,
    ErrorResponse,
)
from src.schemas.two_factor import (
    TwoFAStatusResponse,
    Disable2FARequest,
    Disable2FAResponse,
    RegenerateBackupCodesRequest,
    RegenerateBackupCodesResponse,
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
    has admin-level access (user_type in [ADMIN, SUPER_ADMIN]) and is not blocked.
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

    if not UserType.is_admin_level(account.user_type):
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

    # 2. Must be admin or super admin
    if not UserType.is_admin_level(account.user_type):
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
        user_type=account.user_type,
    )


# ── GET /api/admin/dashboard/summary ─────────────────────────────────

@router.get(
    "/dashboard/summary",
    response_model=AdminDashboardSummary,
)
async def get_dashboard_summary(
    logs_date: Optional[str] = Query(None, description="Date for logs preview (YYYY-MM-DD), defaults to today"),
    logs_level: Optional[str] = Query("all", regex="^(all|info|warn|error)$"),
    logs_page: Optional[int] = Query(1, ge=1, description="Logs page number (1-based)"),
    logs_per_page: Optional[int] = Query(10, ge=1, le=50, description="Logs per page (1-50)"),
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
    recent_users = await _get_recent_users(db, caller_user_type=admin.user_type, limit=3)

    # ── System Logs Preview ─────────────────────────────────────────────
    recent_logs, logs_total_count = _get_logs_preview(
        parsed_logs_date,
        logs_level or "all",
        page=logs_page or 1,
        per_page=logs_per_page or 10,
    )

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
        logs_total_count=logs_total_count,
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
                    available_actions=_available_actions(
                        user_status, acc.user_type, admin.user_type,
                    ),
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

        if account.user_type == UserType.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Cannot delete a super admin account"},
            )

        if account.user_type == UserType.ADMIN and admin.user_type != UserType.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "Cannot delete an admin account"},
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


# ── POST /api/admin/users/{userId}/block ───────────────────────────

@router.post(
    "/users/{userId}/block",
    response_model=ActionResult,
)
async def block_user(
    userId: int,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Block a user account. Operation is idempotent."""
    result = await db.execute(select(Account).where(Account.user_id == userId))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Resource not found"},
        )

    if target.user_type == UserType.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Cannot block/unblock a super admin account"},
        )

    if target.user_type == UserType.ADMIN and admin.user_type != UserType.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Cannot block/unblock an admin account"},
        )

    target.is_blocked = True
    await db.commit()
    logger.info("Admin user_id=%s blocked user_id=%s", admin.user_id, userId)
    return ActionResult(result="success")


# ── POST /api/admin/users/{userId}/unblock ─────────────────────────

@router.post(
    "/users/{userId}/unblock",
    response_model=ActionResult,
)
async def unblock_user(
    userId: int,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Unblock a user account. Operation is idempotent."""
    result = await db.execute(select(Account).where(Account.user_id == userId))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Resource not found"},
        )

    if target.user_type == UserType.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Cannot block/unblock a super admin account"},
        )

    if target.user_type == UserType.ADMIN and admin.user_type != UserType.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Cannot block/unblock an admin account"},
        )

    target.is_blocked = False
    await db.commit()
    logger.info("Admin user_id=%s unblocked user_id=%s", admin.user_id, userId)
    return ActionResult(result="success")


# ── PATCH /api/admin/users/{userId}/role ───────────────────────────

@router.patch(
    "/users/{userId}/role",
    response_model=ActionResult,
    responses={
        400: {"description": "Invalid role value"},
        401: {"description": "Missing, malformed, or expired Bearer token"},
        403: {"description": "Not super admin, or attempting to change own/super admin role"},
        404: {"description": "User not found"},
    },
    summary="Change user role",
)
async def change_user_role(
    userId: int,
    body: ChangeRoleRequest,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change the role (user_type) of a target user. Only super admins can call this."""
    if admin.user_type != UserType.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Super admin permission required"},
        )

    if userId == admin.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Cannot change your own role"},
        )

    if body.role not in UserType.assignable_roles():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Invalid role. Must be one of: 1 (user), 2 (pro_user), 3 (admin)"},
        )

    result = await db.execute(
        select(Account).where(Account.user_id == userId)
    )
    target = result.scalar_one_or_none()

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found"},
        )

    if target.user_type == UserType.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Cannot change the role of a super admin"},
        )

    old_role = target.user_type
    target.user_type = body.role
    await db.commit()

    logger.info(
        "Super admin user_id=%s changed user_id=%s role from %s to %s",
        admin.user_id, userId, old_role, body.role,
    )
    return ActionResult(result="success")


# ── Private helpers ──────────────────────────────────────────────────

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


async def _get_recent_users(
    db: AsyncSession, *, caller_user_type: int, limit: int = 3,
) -> List[AdminUser]:
    """Return the N most recently created accounts."""
    result = await db.execute(
        select(Account).order_by(Account.created_at.desc()).limit(limit)
    )
    accounts = result.scalars().all()

    users: List[AdminUser] = []
    for acc in accounts:
        user_status = _map_status(acc)
        actions = _available_actions(user_status, acc.user_type, caller_user_type)
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


def _available_actions(
    user_status: str,
    target_user_type: int,
    caller_user_type: int,
) -> List[str]:
    """Return available moderation actions based on target status/type and caller role."""
    if target_user_type == UserType.SUPER_ADMIN:
        return []

    if target_user_type == UserType.ADMIN:
        if caller_user_type != UserType.SUPER_ADMIN:
            return []
        actions = ["unblock", "delete", "demote"] if user_status == "blocked" else ["block", "delete", "demote"]
        return actions

    # Regular users (USER / PRO_USER)
    base = ["unblock", "delete"] if user_status == "blocked" else ["block", "delete"]
    if caller_user_type == UserType.SUPER_ADMIN:
        base.append("promote")
    return base


# ── GET /api/admin/auth/2fa/status ──────────────────────────────────

@router.get(
    "/auth/2fa/status",
    response_model=TwoFAStatusResponse,
    summary="Get Admin 2FA Status",
    responses={
        401: {"description": "Invalid or expired token"},
        403: {"description": "Admin permission required"},
    },
)
async def get_admin_2fa_status(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get 2FA status for the current admin user."""
    remaining = 0
    if admin.is_2fa_enabled:
        result = await db.execute(
            select(func.count()).select_from(TotpBackupCode).where(
                TotpBackupCode.user_id == admin.user_id,
                TotpBackupCode.is_used == False,  # noqa: E712
            )
        )
        remaining = result.scalar() or 0

    return TwoFAStatusResponse(
        is_2fa_enabled=admin.is_2fa_enabled,
        backup_codes_remaining=remaining,
    )


# ── GET /api/admin/auth/settings/info ───────────────────────────────

@router.get(
    "/auth/settings/info",
    response_model=GetUserInfoResponse,
    summary="Get Admin User Info",
    responses={
        401: {"description": "Invalid or expired token"},
        403: {"description": "Admin permission required"},
    },
)
async def get_admin_user_info(
    admin: Account = Depends(require_admin),
):
    """Get user information for the current admin user."""
    return GetUserInfoResponse(
        email=admin.email,
        name=admin.user_name,
        user_type=admin.user_type,
    )


# ──────────── Helper functions for device management ──────────────

def _format_browser(ua) -> str:
    """Return '<family> <major>' or 'Unknown'."""
    family = ua.browser.family
    version = ua.browser.version_string
    if not family or family == "Other":
        return "Unknown"
    major = version.split(".")[0] if version else ""
    return f"{family} {major}".strip()


def _format_os(ua) -> str:
    """Return '<os_family> <os_version>' or 'Unknown'."""
    family = ua.os.family
    version = ua.os.version_string
    if not family or family == "Other":
        return "Unknown"
    return f"{family} {version}".strip()


def _parse_device_type(ua) -> str:
    """Map user_agents flags to a device_type string."""
    if ua.is_bot:
        return "Bot"
    if ua.is_tablet:
        return "Tablet"
    if ua.is_mobile:
        return "Mobile"
    if ua.is_pc:
        return "PC"
    return "Unknown"


# ──────────────────────── POST /api/admin/auth/reset ────────────────

@router.post(
    "/auth/reset",
    response_model=ResetPasswordResponse,
    summary="Admin Password Reset Request",
    responses={
        404: {"description": "No account record for this email"},
    },
)
async def admin_reset_password(
    request: ResetPasswordRequest,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Request password reset for admin user using their email."""
    logger.info(f"Admin password reset request for user_id: {admin.user_id}")
    
    # Generate temp token and reset code
    temp_token = create_temp_token()
    reset_code = generate_verification_code()
    
    # Create password reset record with hashed verification code
    reset_record = TempToken(
        user_id=admin.user_id,
        token_hashed=hash_token(temp_token),
        token_type=TokenType.PASSWORD_RESET,
        verification_code_hashed=hash_password(reset_code),
        expire_at=datetime.now(timezone.utc) + timedelta(minutes=5)
    )
    
    db.add(reset_record)
    await db.commit()
    
    # Send reset code via email
    logger.info(f"Password reset temp token created for admin_user_id: {admin.user_id}")
    email_sent = await send_verification_email(
        to_email=admin.email,
        verification_code=reset_code,
        name=admin.user_name,
        email_type="reset"
    )
    
    if not email_sent:
        logger.warning(f"Failed to send reset code email to {admin.email}, but reset record created")
    
    return ResetPasswordResponse(temp_token=temp_token)


# ──────────────────────── POST /api/admin/auth/reset/verify ────────

@router.post(
    "/auth/reset/verify",
    response_model=ConfirmResetPasswordResponse,
    summary="Admin Password Reset Verification",
    responses={
        401: {"description": "Wrong code or expired token"},
    },
)
async def admin_reset_verify(
    request: ConfirmResetPasswordRequest,
    temp_token: str = Header(..., alias="Temp-Token"),
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Verify password reset code and update admin password."""
    logger.info(f"Admin password reset verification for user_id: {admin.user_id}")
    
    temp_token_hashed = hash_token(temp_token)
    
    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token_hashed,
            TempToken.token_type == TokenType.PASSWORD_RESET,
            TempToken.user_id == admin.user_id,
        )
    )
    reset_record = result.scalar_one_or_none()
    
    if not reset_record:
        logger.warning(f"Admin password reset failed: Invalid temp token for user_id={admin.user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Check if expired
    if datetime.now(timezone.utc) > reset_record.expire_at:
        logger.warning(f"Admin password reset failed: Expired token for user_id={admin.user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Verify code against stored hash
    if not reset_record.verification_code_hashed or not verify_password(request.code, reset_record.verification_code_hashed):
        logger.warning(f"Admin password reset failed: Invalid verification code for user_id={admin.user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Wrong code or expired token"}
        )
    
    # Update password
    admin.password_hashed = hash_password(request.newPassword)
    
    # Delete temp token
    await db.delete(reset_record)
    await db.commit()
    
    logger.info(f"Admin password reset successful for user_id={admin.user_id}")
    return ConfirmResetPasswordResponse(message="Password reset successfully")


# ──────────────────────── POST /api/admin/auth/reset/resend ────────

@router.post(
    "/auth/reset/resend",
    response_model=ResendResetCodeResponse,
    summary="Admin Password Reset Resend Code",
    responses={
        401: {"description": "Token expired or invalid"},
        429: {"description": "Too many requests"},
    },
)
async def admin_reset_resend(
    temp_token: str = Header(..., alias="Temp-Token"),
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Resend password reset verification code to admin."""
    logger.info(f"Admin resend reset code for user_id: {admin.user_id}")
    
    temp_token_hashed = hash_token(temp_token)
    
    # Check if temp token exists with correct type
    result = await db.execute(
        select(TempToken).where(
            TempToken.token_hashed == temp_token_hashed,
            TempToken.token_type == TokenType.PASSWORD_RESET,
            TempToken.user_id == admin.user_id,
        )
    )
    reset_record = result.scalar_one_or_none()
    
    if not reset_record:
        logger.warning(f"Admin resend reset code failed: Invalid temp token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired or invalid"}
        )
    
    now = datetime.now(timezone.utc)
    
    # Check if expired
    if now > reset_record.expire_at:
        logger.warning(f"Admin resend reset code failed: Expired token")
        await db.delete(reset_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired or invalid"}
        )
    
    # Rate limit: 60 seconds between resends
    if reset_record.created_at:
        retry_after = 60 - int((now - reset_record.created_at).total_seconds())
        if retry_after > 0:
            logger.warning(f"Admin resend reset code throttled")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Too many requests. Please wait before requesting again.",
                    "retryAfter": retry_after,
                }
            )
    
    # Generate and send new reset code
    reset_code = generate_verification_code()
    email_sent = await send_verification_email(
        to_email=admin.email,
        verification_code=reset_code,
        name=admin.user_name,
        email_type="reset"
    )
    
    if not email_sent:
        logger.warning(f"Failed to resend reset code email to {admin.email}")
    
    # Update verification code hash
    reset_record.verification_code_hashed = hash_password(reset_code)
    await db.commit()
    
    logger.info(f"Admin reset code resent for user_id={admin.user_id}")
    return ResendResetCodeResponse(message="Code resent successfully")


# ──────────────────────── GET /api/admin/auth/settings/devices ────

@router.get(
    "/auth/settings/devices",
    response_model=DevicesResponse,
    summary="Get Admin Device Sessions",
    responses={
        401: {"description": "Invalid or expired token"},
        500: {"description": "Internal server error"},
    },
)
async def admin_get_devices(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """Returns all active login sessions for the current admin user."""
    try:
        # Extract current token hash for is_current comparison
        # Note: admin is already authenticated via require_admin, so we need to get token from headers
        # For simplicity, we'll just return all sessions without is_current distinction
        
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == admin.user_id,
                RefreshToken.expire_at > datetime.now(timezone.utc),
            )
        )
        sessions = result.scalars().all()
        
        devices = []
        for s in sessions:
            ua = parse_ua(s.user_agent or "")
            devices.append(DeviceSession(
                session_id=s.id,
                browser=_format_browser(ua),
                os=_format_os(ua),
                device_type=_parse_device_type(ua),
                created_at=s.created_at.isoformat() if s.created_at else "",
                is_current=False,  # Simplified: not tracking current session
            ))
        
        return DevicesResponse(devices=devices, total=len(devices))
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get admin devices error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ──────────────────────── DELETE /api/admin/auth/settings/devices/{sessionId} ───

@router.delete(
    "/auth/settings/devices/{session_id}",
    response_model=LogoutDeviceResponse,
    summary="Admin Logout Specific Device",
    responses={
        400: {"description": "Cannot logout current device"},
        401: {"description": "Invalid or expired token"},
        404: {"description": "Session not found"},
        500: {"description": "Internal server error"},
    },
)
async def admin_logout_device(
    session_id: int,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """Logout a specific device by session_id."""
    try:
        # Look up the session, ensuring it belongs to the current admin
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.id == session_id,
                RefreshToken.user_id == admin.user_id,
            )
        )
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Session not found"},
            )
        
        token_hashed = session.token_hashed
        
        # Clean Redis cache BEFORE committing the DB delete
        if redis:
            await delete_session_by_hash(redis, token_hashed, admin.user_id)
        
        # Delete from DB
        delete_result = await db.execute(
            sa_delete(RefreshToken).where(
                RefreshToken.id == session_id,
                RefreshToken.user_id == admin.user_id,
            )
        )
        if delete_result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Session not found"},
            )
        await db.commit()
        
        logger.info(f"Admin logout device session_id={session_id} for user_id={admin.user_id}")
        return LogoutDeviceResponse(message="Device session has been logged out")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin logout device error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ──────────────────────── POST /api/admin/auth/settings/logout-all ──

@router.post(
    "/auth/settings/logout-all",
    response_model=dict,
    summary="Admin Logout All Devices",
    responses={
        401: {"description": "Invalid or expired token"},
        500: {"description": "Internal server error"},
    },
)
async def admin_logout_all_devices(
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """Logout all device sessions for the current admin user."""
    try:
        # Fetch all sessions for this user
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.user_id == admin.user_id)
        )
        sessions = result.scalars().all()
        
        revoked_count = len(sessions)
        
        # Delete all from Redis first
        if redis:
            for session in sessions:
                await delete_session_by_hash(redis, session.token_hashed, admin.user_id)
        
        # Delete all from DB
        delete_result = await db.execute(
            sa_delete(RefreshToken).where(RefreshToken.user_id == admin.user_id)
        )
        await db.commit()
        
        logger.info(f"Admin logout all devices for user_id={admin.user_id}, revoked {revoked_count} sessions")
        return {
            "message": "All devices have been logged out",
            "revoked_count": revoked_count
        }
    
    except Exception as e:
        logger.error(f"Admin logout all devices error: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Internal server error"},
        )


# ──────────────────────── POST /api/admin/auth/2fa/disable ───────

@router.post(
    "/auth/2fa/disable",
    response_model=Disable2FAResponse,
    summary="Disable Admin 2FA",
    responses={
        400: {"description": "2FA is not enabled"},
        401: {"description": "Incorrect password"},
    },
)
async def admin_disable_2fa(
    request: Disable2FARequest,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Disable 2FA for admin user."""
    if not admin.is_2fa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "2FA is not enabled"},
        )
    
    # Verify password
    if not verify_password(request.password, admin.password_hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Incorrect password"},
        )
    
    # Clear 2FA data
    admin.is_2fa_enabled = False
    admin.totp_secret_encrypted = None
    
    # Delete all backup codes
    await db.execute(
        sa_delete(TotpBackupCode).where(TotpBackupCode.user_id == admin.user_id)
    )
    
    await db.commit()
    
    logger.info(f"2FA disabled for admin user_id={admin.user_id}")
    return Disable2FAResponse(message="2FA disabled successfully")


# ──────────────────────── POST /api/admin/auth/2fa/backup-codes/regenerate ───

@router.post(
    "/auth/2fa/backup-codes/regenerate",
    response_model=RegenerateBackupCodesResponse,
    summary="Admin Regenerate Backup Codes",
    responses={
        400: {"description": "2FA is not enabled|Invalid TOTP code"},
        401: {"description": "Invalid or expired token"},
    },
)
async def admin_regenerate_backup_codes(
    request: RegenerateBackupCodesRequest,
    admin: Account = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: Optional[Redis] = Depends(get_redis),
):
    """Regenerate backup codes for admin user."""
    if not admin.is_2fa_enabled or not admin.totp_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "2FA is not enabled"},
        )
    
    # Verify TOTP code
    secret = decrypt_secret(admin.totp_secret_encrypted)
    if not verify_totp_code(secret, request.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Invalid TOTP code"},
        )
    
    # Replay protection
    if await check_totp_replay(redis, admin.user_id, request.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "TOTP code already used, please wait for a new code"},
        )
    
    # Delete old backup codes
    await db.execute(
        sa_delete(TotpBackupCode).where(TotpBackupCode.user_id == admin.user_id)
    )
    
    # Generate and persist new codes
    new_codes = generate_backup_codes()
    for code in new_codes:
        db.add(TotpBackupCode(
            user_id=admin.user_id,
            code_hashed=hash_password(code),
        ))
    
    await db.commit()
    
    logger.info(f"Backup codes regenerated for admin user_id={admin.user_id}")
    return RegenerateBackupCodesResponse(backup_codes=new_codes)


# ── Logs helpers ─────────────────────────────────────────────────────

def _get_logs_preview(
    target_date: date,
    level: str,
    *,
    page: int = 1,
    per_page: int = 10,
) -> tuple[List[LogEntry], int]:
    """
    Read log entries from the on-disk log file for the given date and
    level filter.  Returns (paginated entries, total count).
    Entries are newest-first; page is 1-based.
    """
    all_entries = _parse_log_file(target_date, level)
    total = len(all_entries)
    start = (page - 1) * per_page
    end = start + per_page
    page_entries = all_entries[start:end]
    return page_entries, total


def _parse_log_file(target_date: date, level: str) -> List[LogEntry]:
    """
    Parse a single day's log file and return all matching entries
    in newest-first order.
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

        for raw_line in reversed(lines):
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
