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


def assert_verify_signup_200(payload: Dict[str, Any]) -> None:
    assert_login_200(payload)


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
    assert_message_response(payload, "Wrong code or expired token")


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
    assert_message_response(payload, "Wrong code or expired token")


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


# ── Chat module response assertions ───────────────────────────────────────────

def assert_stop_chat_200(payload: Dict[str, Any]) -> None:
    """
    Validates POST /chat/{task_id}/stop 200 response.
    Expected schema: {result: str}
    """
    _assert_fields(payload, ["result"])
    assert isinstance(payload["result"], str), "result must be a string"
    assert payload["result"], "result must be a non-empty string"


def assert_stream_error_event(frame_data: Dict[str, Any]) -> None:
    """
    Validates an SSE error event frame emitted inside a chat stream.
    The chat endpoint never closes the stream with a non-200 HTTP status;
    instead it yields a JSON frame: {event: "error", message: str, ...}
    """
    assert "event" in frame_data, f"SSE frame missing 'event' key: {frame_data}"
    assert frame_data["event"] == "error", \
        f"Expected event='error', got event='{frame_data['event']}'"
    assert "message" in frame_data, f"SSE error frame missing 'message' key: {frame_data}"
    assert isinstance(frame_data["message"], str), "SSE error frame 'message' must be a string"


def assert_chat_messages_200(payload: Dict[str, Any]) -> None:
    """
    Validates GET /chat/messages 200 response.
    Expected schema: {limit: int, has_more: bool, data: list}
    """
    _assert_fields(payload, ["limit", "has_more", "data"])
    assert isinstance(payload["limit"], int) and payload["limit"] > 0, \
        "limit must be a positive integer"
    assert isinstance(payload["has_more"], bool), "has_more must be a boolean"
    assert isinstance(payload["data"], list), "data must be an array"


def assert_conversations_200(payload: Dict[str, Any]) -> None:
    """
    Validates GET /chat/conversations 200 response.
    Expected schema: {limit: int, has_more: bool, data: list[ConversationItem]}
    """
    _assert_fields(payload, ["limit", "has_more", "data"])
    assert isinstance(payload["limit"], int) and payload["limit"] > 0, \
        "limit must be a positive integer"
    assert isinstance(payload["has_more"], bool), "has_more must be a boolean"
    assert isinstance(payload["data"], list), "data must be an array"
    for item in payload["data"]:
        assert isinstance(item, dict), "each conversation must be an object"
        required_keys = {"id", "name", "inputs", "status", "introduction", "created_at", "updated_at"}
        assert required_keys.issubset(item.keys()), \
            f"conversation item missing keys: {required_keys - item.keys()}"
        assert isinstance(item["id"], str), "id must be a string"
        assert isinstance(item["name"], str), "name must be a string"
        assert isinstance(item["created_at"], int), "created_at must be an integer"
        assert isinstance(item["updated_at"], int), "updated_at must be an integer"


def assert_feedback_200(payload: Dict[str, Any]) -> None:
    """
    Validates POST /chat/messages/{message_id}/feedbacks 200 response.
    Expected schema: {result: str}
    """
    _assert_fields(payload, ["result"])
    assert isinstance(payload["result"], str), "result must be a string"
    assert payload["result"], "result must be a non-empty string"


def assert_delete_conversation_200(payload: Dict[str, Any]) -> None:
    """
    Validates DELETE /chat/conversations/{conversation_id} 200 response.
    Expected schema: {result: str}
    """
    _assert_fields(payload, ["result"])
    assert isinstance(payload["result"], str), "result must be a string"
    assert payload["result"], "result must be a non-empty string"


# ── Admin module response assertions ──────────────────────────────────────────

def assert_admin_login_200(payload: Dict[str, Any]) -> None:
    """
    Validates POST /api/admin/auth/login 200 response.
    Expected schema: {id: int, name: str, token: str}
    """
    _assert_fields(payload, ["id", "name", "token"])
    assert isinstance(payload["id"], int), "id must be an integer"
    assert isinstance(payload["name"], str), "name must be a string"
    assert isinstance(payload["token"], str) and payload["token"], "token must be a non-empty string"


def assert_admin_dashboard_summary_200(payload: Dict[str, Any]) -> None:
    """
    Validates GET /api/admin/dashboard/summary 200 response.
    Expected schema:
      {
        total_users: int,
        total_users_delta_week: int | null,
        llm_cost_today: {currency: str, amount: float, budget_per_day: float | null},
        recent_users: [{id, name, email, type, status, created_at, available_actions}],
        recent_logs: [{time, level, message}],
        model_cost_snapshot: {total_requests, avg_latency_seconds, tokens_total, estimated_cost}
      }
    """
    _assert_fields(payload, [
        "total_users", "total_users_delta_week", "llm_cost_today",
        "recent_users", "recent_logs", "logs_total_count", "model_cost_snapshot",
    ])
    assert isinstance(payload["total_users"], int), "total_users must be an integer"
    assert payload["total_users_delta_week"] is None or isinstance(payload["total_users_delta_week"], int), \
        "total_users_delta_week must be int or null"

    # llm_cost_today
    cost = payload["llm_cost_today"]
    assert isinstance(cost, dict), "llm_cost_today must be an object"
    assert "currency" in cost and "amount" in cost, "llm_cost_today missing required fields"

    # recent_users
    assert isinstance(payload["recent_users"], list), "recent_users must be a list"
    for user in payload["recent_users"]:
        for key in ("id", "name", "email", "type", "status", "created_at", "available_actions"):
            assert key in user, f"recent_users item missing '{key}'"
        assert isinstance(user["available_actions"], list), "available_actions must be a list"

    # recent_logs + logs_total_count
    assert isinstance(payload["recent_logs"], list), "recent_logs must be a list"
    assert isinstance(payload["logs_total_count"], int), "logs_total_count must be an integer"
    for log in payload["recent_logs"]:
        for key in ("time", "level", "message"):
            assert key in log, f"recent_logs item missing '{key}'"

    # model_cost_snapshot
    snap = payload["model_cost_snapshot"]
    assert isinstance(snap, dict), "model_cost_snapshot must be an object"
    for key in ("total_requests", "tokens_total", "estimated_cost"):
        assert key in snap, f"model_cost_snapshot missing '{key}'"


def assert_rename_conversation_200(payload: Dict[str, Any]) -> None:
    """
    Validates POST /chat/conversations/{conversation_id}/name 200 response.
    Expected schema: {result: str}
    """
    _assert_fields(payload, ["result"])
    assert isinstance(payload["result"], str), "result must be a string"
    assert payload["result"], "result must be a non-empty string"
