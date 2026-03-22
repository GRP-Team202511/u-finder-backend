"""
Router tests for GET /api/admin/dashboard/summary
"""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from src.config.constants import UserType
from src.schemas.admin import (
    AdminUser,
    LlmCostToday,
    LogEntry,
    ModelCostSnapshot,
    Money,
)
from src.utils.jwt_utils import create_access_token
from tests.routers.utils.response_asserts import (
    assert_admin_dashboard_summary_200,
    assert_message_response,
    assert_validation_error,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

DASHBOARD_URL = "/api/admin/dashboard/summary"


def _make_admin_account(
    *,
    user_id: int = 99,
    user_name: str = "Admin User",
    email: str = "admin@example.com",
    user_type: int = UserType.ADMIN,
    is_blocked: bool = False,
    email_verified: bool = True,
):
    """Return a minimal mock Account for require_admin."""
    acc = MagicMock()
    acc.user_id = user_id
    acc.user_name = user_name
    acc.email = email
    acc.user_type = user_type
    acc.is_blocked = is_blocked
    acc.email_verified = email_verified
    acc.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return acc


def _admin_auth_header(user_id: int = 99) -> dict:
    """Return a Bearer header carrying a real JWT for the given admin user."""
    token = create_access_token(
        data={"sub": str(user_id), "email": "admin@example.com", "user_type": UserType.ADMIN}
    )
    return {"Authorization": f"Bearer {token}"}


def _build_db_results(admin_account, *, total_users=42, delta_week=5):
    """
    Build mock results for the 3 sequential db.execute() calls that happen
    before the patched helpers take over:
      0  require_admin       → scalar_one_or_none() → admin account
      1  total_users         → scalar()             → total_users
      2  total_users_delta_week → scalar()          → delta_week
    """
    r0 = MagicMock()
    r0.scalar_one_or_none.return_value = admin_account

    r1 = MagicMock()
    r1.scalar.return_value = total_users

    r2 = MagicMock()
    r2.scalar.return_value = delta_week

    return [r0, r1, r2]


FAKE_LLM_COST = LlmCostToday(currency="USD", amount=1.2345, budget_per_day=None)
FAKE_RECENT_USERS = [
    AdminUser(
        id=1, name="Recent User", email="user@example.com",
        type="1", status="active",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        available_actions=["block", "delete"],
    )
]
FAKE_LOG_ENTRIES = [
    LogEntry(
        time=datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc),
        level="info", message="Test log message",
    )
]
FAKE_MODEL_COST = ModelCostSnapshot(
    total_requests=100, avg_latency_seconds=1.50,
    tokens_total=50000, estimated_cost=Money(currency="USD", amount=2.5),
)


# ── Auth Failure Tests ────────────────────────────────────────────────────────

class TestDashboardAuth:
    async def test_missing_auth_header(self, client):
        """Request without Authorization header must return 422."""
        response = await client.get(DASHBOARD_URL)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_invalid_token(self, client, mock_db):
        """An invalid / expired Bearer token must return 401."""
        response = await client.get(
            DASHBOARD_URL, headers={"Authorization": "Bearer invalid-token"}
        )

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_user_not_found(self, client, mock_db):
        """Valid token but user_id not in DB must return 401."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        response = await client.get(DASHBOARD_URL, headers=_admin_auth_header())

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_blocked_admin(self, client, mock_db):
        """A blocked admin must return 403."""
        admin = _make_admin_account(is_blocked=True)
        mock_db.execute.return_value.scalar_one_or_none.return_value = admin

        response = await client.get(DASHBOARD_URL, headers=_admin_auth_header())

        assert response.status_code == 403
        assert_message_response(response.json(), "Account is blocked")

    async def test_non_admin_user(self, client, mock_db):
        """A non-admin user must return 403."""
        regular = _make_admin_account(user_type=UserType.USER)
        mock_db.execute.return_value.scalar_one_or_none.return_value = regular

        response = await client.get(DASHBOARD_URL, headers=_admin_auth_header())

        assert response.status_code == 403
        assert_message_response(response.json(), "Admin permission required")

    async def test_invalid_logs_date(self, client, mock_db):
        """An invalid logs_date value must return 422."""
        admin = _make_admin_account()
        # require_admin needs a successful DB lookup first
        r0 = MagicMock()
        r0.scalar_one_or_none.return_value = admin
        mock_db.execute.return_value = r0

        response = await client.get(
            DASHBOARD_URL,
            headers=_admin_auth_header(),
            params={"logs_date": "not-a-date"},
        )

        assert response.status_code == 422
        body = response.json()
        assert body["message"] == "Invalid date format, expected YYYY-MM-DD"


# ── Success Tests ─────────────────────────────────────────────────────────────

class TestDashboardSuccess:
    @patch("src.routers.admin._get_model_cost_snapshot", new_callable=AsyncMock, return_value=FAKE_MODEL_COST)
    @patch("src.routers.admin._get_logs_preview", return_value=(FAKE_LOG_ENTRIES, 1))
    @patch("src.routers.admin._get_recent_users", new_callable=AsyncMock, return_value=FAKE_RECENT_USERS)
    @patch("src.routers.admin._get_llm_cost_today", new_callable=AsyncMock, return_value=FAKE_LLM_COST)
    async def test_dashboard_default_params(
        self, mock_cost_today, mock_users, mock_logs, mock_snapshot, client, mock_db,
    ):
        """Authenticated admin with default params must return full summary."""
        admin = _make_admin_account()
        mock_db.execute.side_effect = _build_db_results(admin)

        response = await client.get(DASHBOARD_URL, headers=_admin_auth_header())

        assert response.status_code == 200
        body = response.json()
        assert_admin_dashboard_summary_200(body)

        # Verify KPI values
        assert body["total_users"] == 42
        assert body["total_users_delta_week"] == 5
        assert body["llm_cost_today"]["amount"] == 1.2345
        assert body["llm_cost_today"]["currency"] == "USD"

        # Verify recent_users
        assert len(body["recent_users"]) == 1
        assert body["recent_users"][0]["id"] == 1
        assert body["recent_users"][0]["name"] == "Recent User"

        # Verify recent_logs
        assert len(body["recent_logs"]) == 1
        assert body["recent_logs"][0]["level"] == "info"

        # Verify model_cost_snapshot
        snap = body["model_cost_snapshot"]
        assert snap["total_requests"] == 100
        assert snap["avg_latency_seconds"] == 1.50
        assert snap["tokens_total"] == 50000
        assert snap["estimated_cost"]["amount"] == 2.5

    @patch("src.routers.admin._get_model_cost_snapshot", new_callable=AsyncMock, return_value=FAKE_MODEL_COST)
    @patch("src.routers.admin._get_logs_preview", return_value=([], 0))
    @patch("src.routers.admin._get_recent_users", new_callable=AsyncMock, return_value=FAKE_RECENT_USERS)
    @patch("src.routers.admin._get_llm_cost_today", new_callable=AsyncMock, return_value=FAKE_LLM_COST)
    async def test_dashboard_with_custom_params(
        self, mock_cost_today, mock_users, mock_logs, mock_snapshot, client, mock_db,
    ):
        """Custom query params (logs_date, logs_level, cost_model, cost_time_range) must be accepted."""
        admin = _make_admin_account()
        mock_db.execute.side_effect = _build_db_results(admin)

        response = await client.get(
            DASHBOARD_URL,
            headers=_admin_auth_header(),
            params={
                "logs_date": "2026-03-01",
                "logs_level": "error",
                "cost_model": "cv_parsing",
                "cost_time_range": "last_7d",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert_admin_dashboard_summary_200(body)

        # Verify helpers received the correct arguments
        mock_logs.assert_called_once_with(date(2026, 3, 1), "error", page=1, per_page=10)
        mock_snapshot.assert_called_once()
        call_args = mock_snapshot.call_args
        assert call_args[1].get("model") or call_args[0][1] == "cv_parsing"

    @patch("src.routers.admin._get_model_cost_snapshot", new_callable=AsyncMock,
           return_value=ModelCostSnapshot(total_requests=0, avg_latency_seconds=None, tokens_total=0, estimated_cost=Money()))
    @patch("src.routers.admin._get_logs_preview", return_value=([], 0))
    @patch("src.routers.admin._get_recent_users", new_callable=AsyncMock, return_value=[])
    @patch("src.routers.admin._get_llm_cost_today", new_callable=AsyncMock,
           return_value=LlmCostToday(currency="USD", amount=0.0))
    async def test_dashboard_zero_values(
        self, mock_cost_today, mock_users, mock_logs, mock_snapshot, client, mock_db,
    ):
        """Dashboard must handle zero / null aggregate values gracefully."""
        admin = _make_admin_account()
        mock_db.execute.side_effect = _build_db_results(admin, total_users=0, delta_week=0)

        response = await client.get(DASHBOARD_URL, headers=_admin_auth_header())

        assert response.status_code == 200
        body = response.json()
        assert_admin_dashboard_summary_200(body)
        assert body["total_users"] == 0
        assert body["total_users_delta_week"] == 0
        assert body["llm_cost_today"]["amount"] == 0.0
        assert body["recent_users"] == []
        assert body["recent_logs"] == []
        assert body["model_cost_snapshot"]["total_requests"] == 0
        assert body["model_cost_snapshot"]["avg_latency_seconds"] is None
