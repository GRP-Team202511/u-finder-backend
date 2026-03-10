"""
Router tests for GET /profile/personal and PUT /profile/personal

Authentication strategy:
  - Successful auth: set mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}
    so that get_session() finds a Redis hit and returns user_id=1 without touching the DB.
  - Failed auth (401): leave hgetall returning {} (falsy) and DB returning None,
    so _get_current_user_id raises HTTP 401.

Multiple sequential DB calls are handled via mock_db.execute.side_effect.
"""
import pytest
from unittest.mock import MagicMock
from tests.routers.utils.response_asserts import (
    assert_personal_info_200,
    assert_message_response,
    assert_validation_error,
)

GET_URL = "/profile/personal"
PUT_URL = "/profile/personal"

VALID_PUT_BODY = {
    "name": "Updated Name",
    "gender": "female",
    "birthday": "2000-01-01",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db_result(value):
    """Return a MagicMock whose scalar_one_or_none() yields the given value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _setup_redis_hit(mock_redis):
    """Configure Redis to return a valid session (auth succeeds via cache)."""
    mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}


# ── GET /profile/personal ─────────────────────────────────────────────────────

class TestGetPersonalInfo:

    async def test_get_personal_success(self, client, mock_db, mock_redis, fake_account, fake_profile, auth_headers):
        """Valid token + existing account + existing profile -> 200 with correct schema."""
        _setup_redis_hit(mock_redis)
        # Two sequential DB execute calls: Account query, then UserProfile query
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(fake_profile),
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert_personal_info_200(body)
        # Verify values come from profile.basic_info
        assert body["name"] == fake_profile.basic_info["name"]
        assert body["gender"] == fake_profile.basic_info["gender"]
        assert body["birthday"] == fake_profile.basic_info["birthday"]

    async def test_get_personal_no_profile_record(self, client, mock_db, mock_redis, fake_account, auth_headers):
        """Valid token + account exists + no UserProfile row -> 200 with fallback defaults."""
        _setup_redis_hit(mock_redis)
        # Account found, but UserProfile is None (new user with no profile yet)
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(None),
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert_personal_info_200(body)
        # No profile row -> name defaults to empty string
        assert body["name"] == ""

    async def test_get_personal_missing_auth_header(self, client):
        """Missing Authorization header -> 422 (FastAPI required header validation)."""
        response = await client.get(GET_URL)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_get_personal_invalid_token(self, client, mock_db, mock_redis, auth_headers):
        """Token not found in Redis or DB -> 401."""
        # Redis miss: hgetall returns empty dict
        mock_redis.hgetall.return_value = {}
        # DB miss: no RefreshToken record
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 401
        # OpenAPI doc expects: {"message": "Invalid or expired token"}
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_get_personal_user_not_found(self, client, mock_db, mock_redis, auth_headers):
        """Token valid but Account record missing -> 404."""
        _setup_redis_hit(mock_redis)
        # Account query returns None
        mock_db.execute.side_effect = [_make_db_result(None)]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 404
        # OpenAPI doc expects: {"message": "User not found"}
        assert_message_response(response.json(), "User not found")


# ── PUT /profile/personal ─────────────────────────────────────────────────────

class TestUpdatePersonalInfo:

    async def test_put_personal_success(self, client, mock_db, mock_redis, fake_account, fake_profile, auth_headers):
        """Valid token + valid body + existing account -> 200 with success message."""
        _setup_redis_hit(mock_redis)
        # Account query, then UserProfile query
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(fake_profile),
        ]

        response = await client.put(PUT_URL, json=VALID_PUT_BODY, headers=auth_headers)

        assert response.status_code == 200
        # OpenAPI doc expects: {"message": "Update successfully"}
        assert_message_response(response.json(), "Update successfully")

    async def test_put_personal_creates_profile_if_missing(self, client, mock_db, mock_redis, fake_account, auth_headers):
        """Valid token + no existing profile row -> 200 (router creates new UserProfile)."""
        _setup_redis_hit(mock_redis)
        # Account found, UserProfile query returns None (will be created)
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(None),
        ]

        response = await client.put(PUT_URL, json=VALID_PUT_BODY, headers=auth_headers)

        assert response.status_code == 200
        assert_message_response(response.json(), "Update successfully")

    async def test_put_personal_missing_auth_header(self, client):
        """Missing Authorization header -> 422."""
        response = await client.put(PUT_URL, json=VALID_PUT_BODY)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_personal_invalid_token(self, client, mock_db, mock_redis, auth_headers):
        """Invalid token (Redis miss + DB miss) -> 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.put(PUT_URL, json=VALID_PUT_BODY, headers=auth_headers)

        assert response.status_code == 401
        # OpenAPI doc expects: {"message": "Invalid or expired token"}
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_put_personal_user_not_found(self, client, mock_db, mock_redis, auth_headers):
        """Token valid but Account missing -> 404."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.side_effect = [_make_db_result(None)]

        response = await client.put(PUT_URL, json=VALID_PUT_BODY, headers=auth_headers)

        assert response.status_code == 404
        # OpenAPI doc expects: {"message": "User not found"}
        assert_message_response(response.json(), "User not found")

    async def test_put_personal_missing_name(self, client, auth_headers):
        """Missing required 'name' field -> 422 (Pydantic validation)."""
        body = {"gender": "male", "birthday": "2000-01-01"}

        response = await client.put(PUT_URL, json=body, headers=auth_headers)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_personal_missing_gender(self, client, auth_headers):
        """Missing required 'gender' field -> 422."""
        body = {"name": "Test User", "birthday": "2000-01-01"}

        response = await client.put(PUT_URL, json=body, headers=auth_headers)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_personal_missing_birthday(self, client, auth_headers):
        """Missing required 'birthday' field -> 422."""
        body = {"name": "Test User", "gender": "male"}

        response = await client.put(PUT_URL, json=body, headers=auth_headers)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_personal_empty_name(self, client, auth_headers):
        """Empty string for 'name' violates min_length=1 -> 422."""
        body = {"name": "", "gender": "male", "birthday": "2000-01-01"}

        response = await client.put(PUT_URL, json=body, headers=auth_headers)

        assert response.status_code == 422
        assert_validation_error(response.json())
