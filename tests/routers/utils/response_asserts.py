"""
Reusable response validators for router tests.
Each helper strictly enforces the schema described in auth.openapi.json.
"""
from typing import Any, Dict, Optional, Sequence


def _assert_fields(payload: Dict[str, Any], required: Sequence[str]) -> None:
    """Ensure payload contains exactly the required fields."""
    assert set(payload.keys()) == set(required), f"Expected fields {required}, got {list(payload.keys())}"


def assert_signup_200(payload: Dict[str, Any]) -> None:
    _assert_fields(payload, ["temp_token"])
    assert isinstance(payload["temp_token"], str) and payload["temp_token"], "temp_token must be non-empty string"


def assert_message_response(payload: Dict[str, Any], message_text: Optional[str] = None) -> None:
    _assert_fields(payload, ["message"])
    assert isinstance(payload["message"], str)
    if message_text is not None:
        assert payload["message"] == message_text


def assert_login_200(payload: Dict[str, Any]) -> None:
    _assert_fields(payload, ["id", "name", "token"])
    assert isinstance(payload["id"], int)
    assert isinstance(payload["name"], str)
    assert isinstance(payload["token"], str) and payload["token"], "token must be non-empty string"


def assert_validation_error(payload: Dict[str, Any]) -> None:
    _assert_fields(payload, ["detail"])
    assert isinstance(payload["detail"], list) and payload["detail"], "detail list should not be empty"
    required_keys = {"loc", "msg", "type"}
    for item in payload["detail"]:
        assert required_keys.issubset(item.keys()), f"detail item missing required keys: {required_keys - item.keys()}"
        assert isinstance(item["loc"], list)
        assert all(isinstance(x, (str, int)) for x in item["loc"])
        assert isinstance(item["msg"], str)
        assert isinstance(item["type"], str)


def assert_token_invalid_response(payload: Dict[str, Any]) -> None:
    assert_message_response(payload, "Token expired or invalid")


def assert_token_expired_response(payload: Dict[str, Any]) -> None:
    assert_message_response(payload, "Token expired")


def assert_detail_message_response(payload: Dict[str, Any], message_text: Optional[str] = None) -> None:
    _assert_fields(payload, ["detail"])
    detail = payload["detail"]
    assert isinstance(detail, dict), "detail payload must be an object"
    assert set(detail.keys()) == {"message"}, "detail object must only contain 'message'"
    assert isinstance(detail["message"], str)
    if message_text is not None:
        assert detail["message"] == message_text


def assert_wrong_code_response(payload: Dict[str, Any]) -> None:
    assert_message_response(payload, "Wrong code")


def assert_wrong_verification_code_response(payload: Dict[str, Any]) -> None:
    assert_message_response(payload, "Wrong verification code")


def assert_reset_200(payload: Dict[str, Any]) -> None:
    _assert_fields(payload, ["temp_token"])
    assert isinstance(payload["temp_token"], str) and payload["temp_token"], "temp_token must be non-empty string"


def assert_reset_verify_200(payload: Dict[str, Any]) -> None:
    assert_message_response(payload, "Password reset successfully")


def assert_rate_limit_response(payload: Dict[str, Any]) -> None:
    _assert_fields(payload, ["message", "retryAfter"])
    assert payload["message"] == "Too many requests. Please wait before requesting again."
    assert isinstance(payload["retryAfter"], int) and payload["retryAfter"] > 0


# ── Profile module response assertions ────────────────────────────────────────

def assert_personal_info_200(payload: Dict[str, Any]) -> None:
    """
    Validates GET /profile/personal 200 response.
    Expected schema: {name: str, gender: str, birthday: str | null}
    """
    _assert_fields(payload, ["name", "gender", "birthday"])
    assert isinstance(payload["name"], str), "name must be a string"
    assert isinstance(payload["gender"], str), "gender must be a string"
    assert payload["birthday"] is None or isinstance(payload["birthday"], str), \
        "birthday must be a string or null"


def assert_array_profile_200(payload: Dict[str, Any]) -> None:
    """
    Validates GET /profile/array/{field} 200 response.
    Expected schema: {data: array}
    """
    _assert_fields(payload, ["data"])
    assert isinstance(payload["data"], list), "data must be an array"


def assert_all_profile_200(payload: Dict[str, Any]) -> None:
    """
    Validates GET /profile 200 response.
    Expected schema:
      {
        personalInfo: {name: str, gender: str, birthday: str},
        education:    {data: []},
        academic:     {data: []},
        test:         {data: []},
        internship:   {data: []},
        project:      {data: []},
        campus:       {data: []},
        award:        {data: []},
      }
    """
    top_level_fields = [
        "personalInfo", "education", "academic", "test",
        "internship", "project", "campus", "award",
    ]
    _assert_fields(payload, top_level_fields)

    # Validate personalInfo sub-object
    personal = payload["personalInfo"]
    assert isinstance(personal, dict), "personalInfo must be an object"
    assert set(personal.keys()) == {"name", "gender", "birthday"}, \
        f"personalInfo must have exactly name, gender, birthday; got {list(personal.keys())}"
    assert isinstance(personal["name"], str), "personalInfo.name must be a string"
    assert isinstance(personal["gender"], str), "personalInfo.gender must be a string"
    assert personal["birthday"] is None or isinstance(personal["birthday"], str), \
        "personalInfo.birthday must be a string or null"

    # Validate each array section: {data: list}
    array_sections = ["education", "academic", "test", "internship", "project", "campus", "award"]
    for section in array_sections:
        section_data = payload[section]
        assert isinstance(section_data, dict), f"{section} must be an object"
        assert set(section_data.keys()) == {"data"}, \
            f"{section} must have exactly one key 'data'; got {list(section_data.keys())}"
        assert isinstance(section_data["data"], list), f"{section}.data must be an array"
