"""
Tests for liked-university endpoints:
  POST /profile/liked-university/check
  POST /profile/liked-university/{unit_id}
  DELETE /profile/liked-university/{unit_id}
  GET  /profile/liked-university
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
# POST /profile/liked-university/check
# 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

class TestCheckFavoriteUniversity:
    """POST /profile/liked-university/check"""

    @pytest.mark.asyncio
    async def test_check_not_liked(
        self, client, mock_db, mock_redis, auth_headers, sample_program_card,
    ):
        """Card not yet liked 鈫?is_liked=false, returns a unit_id."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        fake_program = MagicMock()
        fake_program.id = "550e8400-e29b-41d4-a716-446655440000"
        fake_program.program_data = sample_program_card

        with patch(
            "src.routers.profile.resolve_university_program",
            new_callable=AsyncMock,
            return_value=fake_program,
        ):
            # First call: resolve_university_program
            # Second call: SELECT UserLikedUniversity 鈫?None (not liked)
            exec_result_none = MagicMock()
            exec_result_none.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = exec_result_none

            resp = await client.post(
                "/profile/liked-university/check",
                json=sample_program_card,
                headers=auth_headers,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["unit_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert body["is_liked"] is False

    @pytest.mark.asyncio
    async def test_check_already_liked(
        self, client, mock_db, mock_redis, auth_headers, sample_program_card, fake_liked_record,
    ):
        """Card already liked 鈫?is_liked=true."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        fake_program = MagicMock()
        fake_program.id = "550e8400-e29b-41d4-a716-446655440000"

        with patch(
            "src.routers.profile.resolve_university_program",
            new_callable=AsyncMock,
            return_value=fake_program,
        ):
            exec_result = MagicMock()
            exec_result.scalar_one_or_none.return_value = fake_liked_record
            mock_db.execute.return_value = exec_result

            resp = await client.post(
                "/profile/liked-university/check",
                json=sample_program_card,
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["is_liked"] is True

    @pytest.mark.asyncio
    async def test_check_missing_required_field(self, client, mock_redis, auth_headers):
        """Missing university.name 鈫?422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}
        bad_card = {
            "university": {"official_website": "https://mit.edu"},
            "degree_program": {
                "name": "MS CS",
                "degree_level": "Master",
                "field": "CS",
                "program_type": "Full-time",
            },
            "official_program_url": "https://mit.edu/ms",
        }
        resp = await client.post(
            "/profile/liked-university/check",
            json=bad_card,
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_check_unauthorized(self, client, mock_db, mock_redis, sample_program_card):
        """No auth header 鈫?422 (FastAPI requires header)."""
        resp = await client.post(
            "/profile/liked-university/check",
            json=sample_program_card,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_check_invalid_token(self, client, mock_db, mock_redis, sample_program_card):
        """Invalid token 鈫?401."""
        mock_redis.hgetall.return_value = {}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        resp = await client.post(
            "/profile/liked-university/check",
            json=sample_program_card,
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401


# 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
# POST /profile/liked-university/{unit_id}
# 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

class TestLikeUniversity:
    """POST /profile/liked-university/{unit_id}"""

    VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_like_success(
        self, client, mock_db, mock_redis, auth_headers, fake_university_program,
    ):
        """Like a program that exists 鈫?200, is_liked=true."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # SELECT UniversityProgram 鈫?found
                result.scalar_one_or_none.return_value = fake_university_program
            else:
                # SELECT UserLikedUniversity 鈫?not found (first time liking)
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=side_effect)

        resp = await client.post(
            f"/profile/liked-university/{self.VALID_UUID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["unit_id"] == self.VALID_UUID
        assert body["is_liked"] is True

    @pytest.mark.asyncio
    async def test_like_not_found(self, client, mock_db, mock_redis, auth_headers):
        """Program doesn't exist 鈫?404."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.post(
            f"/profile/liked-university/{self.VALID_UUID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["message"] == "University program not found"

    @pytest.mark.asyncio
    async def test_like_invalid_uuid(self, client, mock_db, mock_redis, auth_headers):
        """Bad UUID 鈫?422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}
        resp = await client.post(
            "/profile/liked-university/not-a-uuid",
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.json()["message"] == "Invalid university program ID format"

    @pytest.mark.asyncio
    async def test_like_idempotent(
        self, client, mock_db, mock_redis, auth_headers, fake_university_program, fake_liked_record,
    ):
        """Liking the same program twice 鈫?still 200."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = fake_university_program
            else:
                result.scalar_one_or_none.return_value = fake_liked_record
            return result

        mock_db.execute = AsyncMock(side_effect=side_effect)

        resp = await client.post(
            f"/profile/liked-university/{self.VALID_UUID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_liked"] is True


# 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
# DELETE /profile/liked-university/{unit_id}
# 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

class TestUnlikeUniversity:
    """DELETE /profile/liked-university/{unit_id}"""

    VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_unlike_success(
        self, client, mock_db, mock_redis, auth_headers, fake_liked_record,
    ):
        """Unlike an existing liked program 鈫?200, is_liked=false."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = fake_liked_record

        resp = await client.delete(
            f"/profile/liked-university/{self.VALID_UUID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["unit_id"] == self.VALID_UUID
        assert body["is_liked"] is False

    @pytest.mark.asyncio
    async def test_unlike_not_liked(self, client, mock_db, mock_redis, auth_headers):
        """Unliking something not liked 鈫?still 200 (idempotent)."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        resp = await client.delete(
            f"/profile/liked-university/{self.VALID_UUID}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_liked"] is False

    @pytest.mark.asyncio
    async def test_unlike_invalid_uuid(self, client, mock_db, mock_redis, auth_headers):
        """Bad UUID 鈫?422."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}
        resp = await client.delete(
            "/profile/liked-university/bad-id",
            headers=auth_headers,
        )
        assert resp.status_code == 422


# 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
# GET /profile/liked-university
# 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

class TestGetLikedUniversities:
    """GET /profile/liked-university"""

    @pytest.mark.asyncio
    async def test_get_empty_list(self, client, mock_db, mock_redis, auth_headers):
        """No liked programs 鈫?empty list."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = exec_result

        resp = await client.get(
            "/profile/liked-university",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_get_with_items(
        self, client, mock_db, mock_redis, auth_headers,
        fake_liked_record, fake_university_program,
    ):
        """One liked program 鈫?list with one item."""
        mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # First call: SELECT UserLikedUniversity list
                result.scalars.return_value.all.return_value = [fake_liked_record]
            else:
                # Second call: SELECT UniversityProgram by id
                result.scalar_one_or_none.return_value = fake_university_program
            return result

        mock_db.execute = AsyncMock(side_effect=side_effect)

        resp = await client.get(
            "/profile/liked-university",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["unit_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert "program" in data[0]
        assert data[0]["program"]["university"]["name"] == "Massachusetts Institute of Technology"

    @pytest.mark.asyncio
    async def test_get_unauthorized(self, client, mock_db, mock_redis):
        """No auth 鈫?422."""
        resp = await client.get("/profile/liked-university")
        assert resp.status_code == 422

