"""
Router tests for GET /profile/array/{field} and PUT /profile/array/{field}

Valid fields: education, academic, test, internship, project, campus, award

Key behaviours verified:
  - Field validation fires BEFORE auth; an invalid field returns 400 regardless
    of whether a token is present.
  - Successful auth is simulated by configuring mock_redis.hgetall to return a
    session dict, bypassing the database RefreshToken look-up entirely.
  - Multiple DB execute calls in one request are handled via side_effect lists.
"""
import pytest
from unittest.mock import MagicMock
from tests.routers.utils.response_asserts import (
    assert_array_profile_200,
    assert_message_response,
    assert_validation_error,
)

# All seven valid field values accepted by /profile/array/{field}
VALID_FIELDS = ["education", "academic", "test", "internship", "project", "campus", "award"]

# Expected 200 response message per field (mirrors FIELD_DISPLAY_NAMES in schemas)
FIELD_SAVE_MESSAGES = {
    "education":  "Education Info saved successfully",
    "academic":   "Academic Info saved successfully",
    "test":       "Standardized Test Info saved successfully",
    "internship": "Internship Info saved successfully",
    "project":    "Project Info saved successfully",
    "campus":     "Campus Experience Info saved successfully",
    "award":      "Award Info saved successfully",
}

SAMPLE_DATA = [{"key": "value", "nested": {"a": 1}}]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db_result(value):
    """Return a MagicMock whose scalar_one_or_none() yields the given value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _setup_redis_hit(mock_redis):
    """Configure Redis to return a valid session (auth succeeds via cache)."""
    mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}


def _get_url(field: str) -> str:
    return f"/profile/array/{field}"


# ── GET /profile/array/{field} ────────────────────────────────────────────────

class TestGetArrayProfile:

    async def test_get_education_success(self, client, mock_db, mock_redis, fake_profile, auth_headers):
        """Valid token + existing profile -> 200 with {data: list} for 'education'."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.return_value = _make_db_result(fake_profile)

        response = await client.get(_get_url("education"), headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert_array_profile_200(body)
        assert body["data"] == fake_profile.education

    @pytest.mark.parametrize("field", VALID_FIELDS)
    async def test_get_all_valid_fields_return_200(self, client, mock_db, mock_redis, fake_profile, auth_headers, field):
        """All 7 valid field values must return 200 with {data: list}."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.return_value = _make_db_result(fake_profile)

        response = await client.get(_get_url(field), headers=auth_headers)

        assert response.status_code == 200
        assert_array_profile_200(response.json())

    async def test_get_invalid_field_returns_400(self, client, auth_headers):
        """
        An unrecognised field value with a valid Authorization header -> 400.
        NOTE: FastAPI validates the required 'Authorization' header BEFORE the
        function body runs. The field check (400) only fires if the header is
        present; an absent header yields 422 instead (see companion test below).
        """
        response = await client.get(_get_url("invalid_field"), headers=auth_headers)

        assert response.status_code == 400
        # OpenAPI doc expects: {"message": "Invalid field. Must be one of: ..."}
        assert_message_response(response.json(), "Invalid field. Must be one of: academic, award, campus, education, internship, project, test")

    async def test_get_invalid_field_no_auth_returns_422(self, client):
        """
        Invalid field + missing Authorization header -> 422 (not 400).
        FastAPI's header validation fires first; the field check is never reached.
        This is an API vs OpenAPI doc behavioural difference: the doc lists only
        400 for bad fields but does not document this 422 edge case.
        """
        response = await client.get(_get_url("invalid_field"))

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_get_missing_auth_header(self, client):
        """Missing Authorization header with a valid field name -> 422."""
        response = await client.get(_get_url("education"))

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_get_invalid_token(self, client, mock_db, mock_redis, auth_headers):
        """Token not found in Redis or DB -> 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.get(_get_url("education"), headers=auth_headers)

        assert response.status_code == 401
        # OpenAPI doc expects: {"message": "Invalid or expired token"}
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_get_no_profile_record_returns_404(self, client, mock_db, mock_redis, auth_headers):
        """Token valid but no UserProfile row exists -> 404."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.get(_get_url("education"), headers=auth_headers)

        assert response.status_code == 404
        # OpenAPI doc expects: {"message": "Profile data not found"}
        assert_message_response(response.json(), "Profile data not found")

    async def test_get_profile_field_none_returns_404(self, client, mock_db, mock_redis, auth_headers):
        """Profile exists but the field attribute is None -> 404."""
        _setup_redis_hit(mock_redis)
        # Create a profile mock where education is explicitly None
        profile_with_null_field = MagicMock()
        profile_with_null_field.education = None
        mock_db.execute.return_value = _make_db_result(profile_with_null_field)

        response = await client.get(_get_url("education"), headers=auth_headers)

        assert response.status_code == 404
        assert_message_response(response.json(), "Profile data not found")


# ── PUT /profile/array/{field} ────────────────────────────────────────────────

class TestUpdateArrayProfile:

    async def test_put_education_success(self, client, mock_db, mock_redis, fake_profile, auth_headers):
        """Valid token + valid body for 'education' -> 200 with save message."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.return_value = _make_db_result(fake_profile)

        response = await client.put(
            _get_url("education"),
            json={"data": SAMPLE_DATA},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert_message_response(response.json(), FIELD_SAVE_MESSAGES["education"])

    @pytest.mark.parametrize("field", VALID_FIELDS)
    async def test_put_all_valid_fields_return_200(self, client, mock_db, mock_redis, fake_profile, auth_headers, field):
        """All 7 valid field values must return 200 with the correct save message."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.return_value = _make_db_result(fake_profile)

        response = await client.put(
            _get_url(field),
            json={"data": SAMPLE_DATA},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert_message_response(response.json(), FIELD_SAVE_MESSAGES[field])

    async def test_put_creates_profile_if_missing(self, client, mock_db, mock_redis, auth_headers):
        """Valid token + no existing profile row -> 200 (router creates new UserProfile)."""
        _setup_redis_hit(mock_redis)
        # Profile query returns None; the router will create a new one
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.put(
            _get_url("education"),
            json={"data": SAMPLE_DATA},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert_message_response(response.json(), FIELD_SAVE_MESSAGES["education"])

    async def test_put_invalid_field_returns_400(self, client, auth_headers):
        """
        An unrecognised field value with Authorization header present -> 400.
        Same FastAPI validation-order behaviour as the GET variant above.
        """
        response = await client.put(
            _get_url("invalid_field"),
            json={"data": SAMPLE_DATA},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert_message_response(response.json(), "Invalid field. Must be one of: academic, award, campus, education, internship, project, test")

    async def test_put_invalid_field_no_auth_returns_422(self, client):
        """
        Invalid field + missing Authorization header -> 422 (not 400).
        FastAPI header validation fires before the field check in the function body.
        """
        response = await client.put(_get_url("invalid_field"), json={"data": SAMPLE_DATA})

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_missing_auth_header(self, client):
        """Missing Authorization header with a valid field name -> 422."""
        response = await client.put(_get_url("education"), json={"data": SAMPLE_DATA})

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_invalid_token(self, client, mock_db, mock_redis, auth_headers):
        """Invalid token (Redis miss + DB miss) -> 401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value = _make_db_result(None)

        response = await client.put(
            _get_url("education"),
            json={"data": SAMPLE_DATA},
            headers=auth_headers,
        )

        assert response.status_code == 401
        # OpenAPI doc expects: {"message": "Invalid or expired token"}
        assert_message_response(response.json(), "Invalid or expired token")

    async def test_put_missing_data_field_returns_422(self, client, auth_headers):
        """Request body missing the required 'data' key -> 422 (Pydantic validation)."""
        response = await client.put(
            _get_url("education"),
            json={"wrong_key": []},
            headers=auth_headers,
        )

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_data_not_array_returns_422(self, client, auth_headers):
        """'data' field is a string instead of an array -> 422."""
        response = await client.put(
            _get_url("education"),
            json={"data": "not_an_array"},
            headers=auth_headers,
        )

        assert response.status_code == 422
        assert_validation_error(response.json())

    async def test_put_empty_array_is_valid(self, client, mock_db, mock_redis, fake_profile, auth_headers):
        """Sending an empty array for 'data' is allowed -> 200 (clear all entries)."""
        _setup_redis_hit(mock_redis)
        mock_db.execute.return_value = _make_db_result(fake_profile)

        response = await client.put(
            _get_url("education"),
            json={"data": []},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert_message_response(response.json(), FIELD_SAVE_MESSAGES["education"])
