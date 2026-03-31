# This code was completed by GRP Team 2025.11.
"""
University program deduplication service.

Dedup pipeline:
  L1 — official_program_url exact match (after URL normalization)
  L2 — university name + program name + degree level (after text normalization)
"""
import re
import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.logger import get_logger
from src.database.models import UniversityProgram
from src.schemas.profile import ProgramCardRequest

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Normalization helpers
# ──────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """Normalize a URL for dedup comparison.

    - Strip whitespace
    - Lowercase
    - Remove scheme (http:// / https://)
    - Remove leading 'www.'
    - Remove trailing '/'
    - Remove query string and fragment
    """
    url = url.strip().lower()
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def normalize_name(university_name: str, program_name: str, degree_level: str) -> str:
    """Build a normalized composite key for L2 dedup.

    Lowercase → strip → collapse whitespace → remove non-alphanumeric (except spaces).
    """
    raw = f"{university_name} | {program_name} | {degree_level}"
    result = raw.lower().strip()
    result = re.sub(r"[^a-z0-9\s|]", "", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def _card_to_dict(card: ProgramCardRequest) -> dict:
    """Convert a ProgramCardRequest to a plain dict suitable for JSONB storage."""
    return card.model_dump(mode="json")


# ──────────────────────────────────────────────
# Core resolve function
# ──────────────────────────────────────────────

async def resolve_university_program(
    db: AsyncSession,
    card: ProgramCardRequest,
) -> UniversityProgram:
    """Find an existing UniversityProgram or create a new one.

    Pipeline: L1 (URL match) → L2 (normalized name match) → create new.
    The caller is responsible for calling ``await db.commit()`` afterwards.
    """
    n_url = normalize_url(card.official_program_url) if card.official_program_url else None
    n_name = normalize_name(
        card.university.name,
        card.degree_program.name,
        card.degree_program.degree_level,
    )

    # L1: URL exact match
    if n_url:
        result = await db.execute(
            select(UniversityProgram).where(UniversityProgram.normalized_url == n_url)
        )
        existing = result.scalar_one_or_none()
        if existing:
            # Update program_data with latest LLM info
            existing.program_data = _card_to_dict(card)
            logger.debug("L1 URL match: id=%s url=%s", existing.id, n_url)
            return existing

    # L2: normalized name match
    result = await db.execute(
        select(UniversityProgram).where(UniversityProgram.normalized_name == n_name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        # Backfill URL if previously missing
        if n_url and not existing.normalized_url:
            existing.normalized_url = n_url
        existing.program_data = _card_to_dict(card)
        logger.debug("L2 name match: id=%s name=%s", existing.id, n_name)
        return existing

    # No match — create new
    program = UniversityProgram(
        id=str(uuid.uuid4()),
        normalized_url=n_url,
        normalized_name=n_name,
        program_data=_card_to_dict(card),
    )
    db.add(program)
    await db.flush()  # Populate id; caller commits the transaction
    logger.info("Created new university program: id=%s name=%s", program.id, n_name)
    return program
