"""
Unit tests for src/services/university_service.py

Covers:
  - URL normalization
  - Name normalization
  - resolve_university_program dedup pipeline (L1, L2, create new)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.university_service import (
    normalize_url,
    normalize_name,
    resolve_university_program,
)
from src.schemas.profile import ProgramCardRequest


# ──────────────────────────────────────────────
# normalize_url
# ──────────────────────────────────────────────

class TestNormalizeUrl:

    def test_strips_scheme_and_www(self):
        assert normalize_url("https://www.mit.edu/") == "mit.edu"

    def test_strips_http(self):
        assert normalize_url("http://example.com/path/") == "example.com/path"

    def test_preserves_path(self):
        assert normalize_url("https://www.eecs.mit.edu/academics/ms-program/") == "eecs.mit.edu/academics/ms-program"

    def test_removes_query_and_fragment(self):
        assert normalize_url("https://mit.edu/page?ref=abc#section") == "mit.edu/page"

    def test_lowercase(self):
        assert normalize_url("HTTPS://WWW.MIT.EDU/Page") == "mit.edu/page"

    def test_strips_whitespace(self):
        assert normalize_url("  https://mit.edu/  ") == "mit.edu"

    def test_no_scheme(self):
        assert normalize_url("mit.edu/path") == "mit.edu/path"


# ──────────────────────────────────────────────
# normalize_name
# ──────────────────────────────────────────────

class TestNormalizeName:

    def test_basic(self):
        result = normalize_name("MIT", "MS in CS", "Master")
        assert result == "mit | ms in cs | master"

    def test_removes_punctuation(self):
        result = normalize_name(
            "Massachusetts Institute of Technology",
            "Master's of Science (Computer Science)",
            "Master",
        )
        assert "'" not in result
        assert "(" not in result
        assert ")" not in result

    def test_collapses_whitespace(self):
        result = normalize_name("  MIT  ", "  MS   CS  ", "  Master  ")
        assert "  " not in result

    def test_case_insensitive(self):
        r1 = normalize_name("MIT", "MS CS", "MASTER")
        r2 = normalize_name("mit", "ms cs", "master")
        assert r1 == r2


# ──────────────────────────────────────────────
# resolve_university_program
# ──────────────────────────────────────────────

def _make_card(**overrides) -> ProgramCardRequest:
    """Build a minimal valid ProgramCardRequest."""
    data = {
        "university": {
            "name": "MIT",
            "country": "US",
            "city": "Cambridge",
            "official_website": "https://mit.edu",
        },
        "degree_program": {
            "name": "MS CS",
            "degree_level": "Master",
            "field": "Computer Science",
            "program_type": "Full-time",
        },
        "official_program_url": "https://www.eecs.mit.edu/ms/",
    }
    data.update(overrides)
    return ProgramCardRequest(**data)


class TestResolveUniversityProgram:

    @pytest.mark.asyncio
    async def test_l1_url_match(self):
        """Existing program found by URL → returns it, no insert."""
        existing = MagicMock()
        existing.id = "existing-uuid"
        existing.normalized_url = "eecs.mit.edu/ms"

        db = AsyncMock()
        # L1 query returns the existing record
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = existing
        db.execute.return_value = exec_result

        card = _make_card()
        result = await resolve_university_program(db, card)

        assert result.id == "existing-uuid"
        db.add.assert_not_called()
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_l2_name_match(self):
        """L1 misses, L2 name matches → returns existing."""
        existing = MagicMock()
        existing.id = "name-match-uuid"
        existing.normalized_url = None  # had no URL before

        db = AsyncMock()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # L1: no URL match
                result.scalar_one_or_none.return_value = None
            else:
                # L2: name match
                result.scalar_one_or_none.return_value = existing
            return result

        db.execute = AsyncMock(side_effect=side_effect)

        card = _make_card()
        result = await resolve_university_program(db, card)

        assert result.id == "name-match-uuid"
        # Should backfill URL
        assert result.normalized_url is not None
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_new(self):
        """Neither L1 nor L2 matches → creates new record."""
        db = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = None
        db.execute.return_value = exec_result
        db.add = MagicMock()

        card = _make_card()
        result = await resolve_university_program(db, card)

        # New program created
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result.normalized_url == "eecs.mit.edu/ms"
        assert result.normalized_name == normalize_name("MIT", "MS CS", "Master")
        assert result.program_data is not None
