# This code was completed by GRP Team 2025.11.
"""
Router tests for GET /profile and PUT /profile

GET /profile returns the complete profile snapshot:
  { personalInfo, education, academic, test, internship, project, campus, award }

PUT /profile updates all sections in a single request and expects the
same full structure in the request body.

Authentication strategy: same as other profile tests.
  - Redis hit  → session found, auth passes without DB RefreshToken look-up.
  - Redis miss → DB queried; returning None raises HTTP 401.
"""
import pytest
from unittest.mock import MagicMock
from tests.routers.utils.response_asserts import (
    assert_all_profile_200,
    assert_message_response,
    assert_validation_error,
)

GET_URL = "/profile"
PUT_URL = "/profile"

# Minimal valid body for PUT /profile (all 8 top-level fields required)
VALID_PUT_BODY = {
    "personalInfo": {
        "name": "Test User",
        "gender": "male",
        "birthday": "2002-07-15",
    },
    "education":  {"data": [{"type": "undergraduate", "name": "Test University"}]},
    "academic":   {"data": [{"type": "research paper", "title": "Sample Paper"}]},
    "test":       {"data": [{"type": "IELTS", "overall": "7.5"}]},
    "internship": {"data": [{"company": "Test Corp", "role": "Intern"}]},
    "project":    {"data": [{"name": "Sample Project"}]},
    "campus":     {"data": [{"name": "Test Society"}]},
    "award":      {"data": [{"name": "Merit Scholarship"}]},
}

# PUT body with every array section empty (edge case: clear all data)
EMPTY_ARRAYS_PUT_BODY = {
    "personalInfo": {"name": "Test User", "gender": "male", "birthday": "2000-01-01"},
    "education":    {"data": []},
    "academic":     {"data": []},
    "test":         {"data": []},
    "internship":   {"data": []},
    "project":      {"data": []},
    "campus":       {"data": []},
    "award":        {"data": []},
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


# ── GET /profile ──────────────────────────────────────────────────────────────

class TestGetAllProfile:

    async def test_get_all_profile_success(
        self, client, mock_db, mock_redis, fake_account, fake_profile, auth_headers
    ):
        """Valid token + existing account and profile -> 200 with full schema."""
        _setup_redis_hit(mock_redis)
        # Two sequential DB calls: Account, then UserProfile
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(fake_profile),
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)

        # Verify personalInfo comes from fake_profile.basic_info
        assert body["personalInfo"]["name"]     == fake_profile.basic_info["name"]
        assert body["personalInfo"]["gender"]   == fake_profile.basic_info["gender"]
        assert body["personalInfo"]["birthday"] == fake_profile.basic_info["birthday"]

        # Verify array sections are non-empty lists (from fake_profile data)
        assert isinstance(body["education"]["data"], list)
        assert len(body["education"]["data"]) > 0

    async def test_get_all_profile_no_profile_row(
        self, client, mock_db, mock_redis, fake_account, auth_headers
    ):
        """
        Valid token + account exists, but no UserProfile row yet -> 200
        with fallback defaults (name from account, empty arrays).
        """
        _setup_redis_hit(mock_redis)
        # Account found, UserProfile returns None (new user)
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(None),
        ]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)
        # No profile row -> name defaults to empty string
        assert body["personalInfo"]["name"] == ""
        # All array sections are empty lists
        for section in ["education", "academic", "test", "internship", "project", "campus", "award"]:
            assert body[section]["data"] == []

    async def test_get_all_profile_missing_auth_header(self, client):
        """Missing Authorization header -> 422 (FastAPI header validation)."""
        response = await client.get(GET_URL)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_get_all_profile_invalid_token(
        self, client, mock_db, mock_redis, auth_headers
    ):
        """Token not found in Redis or DB -> 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 401
        # OpenAPI doc expects: {"message": "Invalid or expired token"}
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_get_all_profile_user_not_found(
        self, client, mock_db, mock_redis, auth_headers
    ):
        """Token valid but Account record missing -> 404."""
        _setup_redis_hit(mock_redis)
        # Account query returns None
        mock_db.execute.side_effect = [_make_db_result(None)]

        response = await client.get(GET_URL, headers=auth_headers)

        assert response.status_code == 404
        # OpenAPI doc expects: {"message": "Profile not found"}
        assert_message_response(response.json(), "Profile not found")


# ── PUT /profile ──────────────────────────────────────────────────────────────

class TestUpdateAllProfile:

    async def test_put_all_profile_success(
        self, client, mock_db, mock_redis, fake_account, fake_profile, auth_headers
    ):
        """Valid token + complete body -> 200 with success message."""
        _setup_redis_hit(mock_redis)
        # Account found, UserProfile found (to be updated)
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(fake_profile),
        ]

        response = await client.put(PUT_URL, json=VALID_PUT_BODY, headers=auth_headers)

        assert response.status_code == 200
        # OpenAPI doc expects: {"message": "All profiles updated successfully"}
        assert_message_response(response.json(), "All profiles updated successfully")

    async def test_put_all_profile_creates_profile_if_missing(
        self, client, mock_db, mock_redis, fake_account, auth_headers
    ):
        """Valid token + no existing profile row -> 200 (router creates new UserProfile)."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(None),
        ]

        response = await client.put(PUT_URL, json=VALID_PUT_BODY, headers=auth_headers)

        assert response.status_code == 200
        assert_message_response(response.json(), "All profiles updated successfully")

    async def test_put_all_profile_empty_arrays(
        self, client, mock_db, mock_redis, fake_account, fake_profile, auth_headers
    ):
        """Sending empty arrays for all sections is valid -> 200 (clears all data)."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.side_effect = [
            _make_db_result(fake_account),
            _make_db_result(fake_profile),
        ]

        response = await client.put(PUT_URL, json=EMPTY_ARRAYS_PUT_BODY, headers=auth_headers)

        assert response.status_code == 200
        assert_message_response(response.json(), "All profiles updated successfully")

    async def test_put_all_profile_missing_auth_header(self, client):
        """Missing Authorization header -> 422."""
        response = await client.put(PUT_URL, json=VALID_PUT_BODY)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_all_profile_invalid_token(
        self, client, mock_db, mock_redis, auth_headers
    ):
        """Invalid token (Redis miss + DB miss) -> 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.put(PUT_URL, json=VALID_PUT_BODY, headers=auth_headers)

        assert response.status_code == 401
        # OpenAPI doc expects: {"message": "Invalid or expired token"}
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_put_all_profile_user_not_found(
        self, client, mock_db, mock_redis, auth_headers
    ):
        """Token valid but Account missing -> 404."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.side_effect = [_make_db_result(None)]

        response = await client.put(PUT_URL, json=VALID_PUT_BODY, headers=auth_headers)

        assert response.status_code == 404
        # OpenAPI doc expects: {"message": "Profile data not found"}
        assert_message_response(response.json(), "Profile data not found")

    async def test_put_all_profile_missing_personal_info(self, client, auth_headers):
        """Missing 'personalInfo' top-level key -> 422 (Pydantic validation)."""
        body = {k: v for k, v in VALID_PUT_BODY.items() if k != "personalInfo"}

        response = await client.put(PUT_URL, json=body, headers=auth_headers)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_all_profile_missing_section(self, client, auth_headers):
        """Missing one array section key (e.g. 'education') -> 422."""
        body = {k: v for k, v in VALID_PUT_BODY.items() if k != "education"}

        response = await client.put(PUT_URL, json=body, headers=auth_headers)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_all_profile_personal_info_missing_name(self, client, auth_headers):
        """personalInfo.name is missing -> 422."""
        body = {**VALID_PUT_BODY, "personalInfo": {"gender": "male", "birthday": "2002-07-15"}}

        response = await client.put(PUT_URL, json=body, headers=auth_headers)

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_all_profile_section_data_not_array(self, client, auth_headers):
        """An array section's 'data' value is not a list -> 422."""
        body = {**VALID_PUT_BODY, "education": {"data": "not_an_array"}}

        response = await client.put(PUT_URL, json=body, headers=auth_headers)

        assert response.status_code == 422
        assert_validation_error(response.json())
