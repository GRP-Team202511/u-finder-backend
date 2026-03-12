"""
LLM Usage Service
Persists per-request Dify usage data to the llm_usage_log table.
"""
from typing import Optional

from src.config.logger import get_logger
from src.database.connection import AsyncSessionLocal
from src.database.models import LlmUsageLog

logger = get_logger(__name__)


async def record_chat_usage(
    *,
    user_id: int,
    usage: dict,
    endpoint: str = "/api/chat/send",
) -> None:
    """
    Persist a single chat message_end usage record.

    Args:
        user_id:  The authenticated user's ID.
        usage:    Dict produced by the ``on_message_end`` callback in
                  ``stream_dify_chat``, containing keys like
                  ``total_tokens``, ``prompt_tokens``, ``completion_tokens``,
                  ``latency``, ``total_price``, ``currency``,
                  ``conversation_id``, ``message_id``.
        endpoint: The originating API route.
    """
    try:
        async with AsyncSessionLocal() as session:
            latency = _safe_float(usage.get("latency"))
            price = usage.get("total_price")
            row = LlmUsageLog(
                user_id=user_id,
                source="chat",
                endpoint=endpoint,
                prompt_tokens=_safe_int(usage.get("prompt_tokens")),
                completion_tokens=_safe_int(usage.get("completion_tokens")),
                total_tokens=_safe_int(usage.get("total_tokens")) or 0,
                latency_seconds=str(latency) if latency is not None else None,
                total_price=str(price) if price is not None else None,
                currency=usage.get("currency") or "USD",
                dify_message_id=usage.get("message_id"),
                dify_conversation_id=usage.get("conversation_id"),
            )
            session.add(row)
            await session.commit()
            logger.debug(
                "Recorded chat usage: user=%s tokens=%s price=%s",
                user_id, row.total_tokens, row.total_price,
            )
    except Exception as exc:
        logger.warning("Failed to persist chat usage: %s", exc)


async def record_workflow_usage(
    *,
    user_id: int,
    usage: dict,
    endpoint: str = "/api/profile/cv-upload",
) -> None:
    """
    Persist a single workflow execution usage record.

    Args:
        user_id:  The authenticated user's ID.
        usage:    Dict produced by ``run_cv_parsing_workflow`` containing
                  ``total_tokens``, ``elapsed_time``, ``total_steps``,
                  ``workflow_run_id``.
        endpoint: The originating API route.
    """
    try:
        async with AsyncSessionLocal() as session:
            latency = _safe_float(usage.get("elapsed_time"))
            row = LlmUsageLog(
                user_id=user_id,
                source="cv_parsing",
                endpoint=endpoint,
                total_tokens=_safe_int(usage.get("total_tokens")) or 0,
                latency_seconds=str(latency) if latency is not None else None,
                total_steps=_safe_int(usage.get("total_steps")),
                dify_workflow_run_id=usage.get("workflow_run_id"),
                # Workflow responses don't include price — leave null
                total_price=None,
                currency="USD",
            )
            session.add(row)
            await session.commit()
            logger.debug(
                "Recorded workflow usage: user=%s tokens=%s elapsed=%s",
                user_id, row.total_tokens, row.latency_seconds,
            )
    except Exception as exc:
        logger.warning("Failed to persist workflow usage: %s", exc)


# ── Helpers ──────────────────────────────────────────────────────────

def _safe_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
