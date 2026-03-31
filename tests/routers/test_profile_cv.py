# This code was completed by GRP Team 2025.11.
"""
Router tests for POST /profile/cv

Covers every documented response status:
  200 — CV parsed successfully (full AllProfileResponse schema)
  400 — No file uploaded / uploaded file is empty
  401 — Missing or invalid JWT token
  413 — File too large (>10 MB)
  415 — Unsupported file type (only PDF & DOCX)
  422 — AI failed to extract structured data
  500 — Unexpected internal error
  502 — Dify AI service unavailable
"""
import json
import pytest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from src.services.dify_service import DifyUpstreamError
from tests.routers.utils.response_asserts import (
    assert_all_profile_200,
    assert_message_response,
)

CV_URL = "/profile/cv"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _setup_redis_hit(mock_redis):
    """Configure Redis to return a valid session (auth succeeds via cache)."""
    mock_redis.hgetall.return_value = {"user_id": "1", "user_agent": "pytest"}


# Realistic Dify workflow outputs (what run_cv_parsing_workflow returns)
FAKE_DIFY_OUTPUTS = {
    "personalInfo": {
        "name": "Zhang San",
        "gender": "male",
        "birthday": "1999-05-20",
    },
    "education": [
        {"type": "undergraduate", "name": "Peking University", "major": "CS"},
    ],
    "academic": [
        {"type": "research paper", "title": "Deep Learning in NLP"},
    ],
    "test": [
        {"type": "IELTS", "overall": "7.5"},
    ],
    "internship": [
        {"company": "ByteDance", "role": "Backend Intern"},
    ],
    "project": [
        {"name": "U-Finder", "role": "Developer"},
    ],
    "campus": [
        {"name": "ACM Club", "description": "Algorithm competition club"},
    ],
    "award": [
        {"name": "National Scholarship"},
    ],
}

# Dify outputs where sections are JSON strings (Dify sometimes returns this)
FAKE_DIFY_OUTPUTS_JSON_STRINGS = {
    "personalInfo": json.dumps({"name": "Li Si", "gender": "female", "birthday": "2000-01-01"}),
    "education": json.dumps([{"type": "master", "name": "Tsinghua University"}]),
    "academic": json.dumps([]),
    "test": json.dumps([{"type": "GRE", "score": "330"}]),
    "internship": "[]",
    "project": "[]",
    "campus": "[]",
    "award": "[]",
}

# Dify outputs wrapped in a "result" key (real Dify workflow behaviour)
FAKE_DIFY_OUTPUTS_WRAPPED = {
    "result": {
        "personalInfo": {
            "name": "Wang Wu",
            "gender": "female",
            "birthday": "2001-03-15",
        },
        "education": [
            {"type": "master", "name": "Fudan University", "major": "AI"},
        ],
        "academic": [],
        "test": [],
        "internship": [],
        "project": [],
        "campus": [],
        "award": [],
    }
}

# Dify outputs where "result" value is a JSON string
FAKE_DIFY_OUTPUTS_WRAPPED_JSON_STRING = {
    "result": json.dumps({
        "personalInfo": {
            "name": "Zhao Liu",
            "gender": "male",
            "birthday": "1998-12-01",
        },
        "education": [],
        "academic": [],
        "test": [],
        "internship": [],
        "project": [],
        "campus": [],
        "award": [],
    })
}

# Dify outputs with null values in personalInfo fields
FAKE_DIFY_OUTPUTS_NULL_FIELDS = {
    "personalInfo": {
        "name": "Test User",
        "gender": None,
        "birthday": None,
    },
    "education": [],
    "academic": [],
    "test": [],
    "internship": [],
    "project": [],
    "campus": [],
    "award": [],
}


def _pdf_file_tuple(content: bytes = b"%PDF-1.4 fake content", filename: str = "resume.pdf"):
    """Build a multipart file tuple for httpx upload."""
    return ("file", (filename, content, "application/pdf"))


def _docx_file_tuple(content: bytes = b"PK\x03\x04 fake docx", filename: str = "resume.docx"):
    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return ("file", (filename, content, ct))


# ── 200: Success ──────────────────────────────────────────────────────────────

class TestCVUploadSuccess:

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_cv_upload_pdf_success(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """PDF upload → Dify returns dict outputs → 200 with full schema."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.return_value = FAKE_DIFY_OUTPUTS

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)
        assert body["personalInfo"]["name"] == "Zhang San"
        assert body["personalInfo"]["gender"] == "male"
        assert body["personalInfo"]["birthday"] == "1999-05-20"
        assert len(body["education"]["data"]) == 1
        assert body["education"]["data"][0]["name"] == "Peking University"
        assert len(body["internship"]["data"]) == 1

        # Verify Dify service was called with correct args
        mock_upload.assert_awaited_once()
        call_kwargs = mock_upload.call_args.kwargs
        assert call_kwargs["filename"] == "resume.pdf"
        assert call_kwargs["content_type"] == "application/pdf"
        assert call_kwargs["user"] == "1"

        mock_workflow.assert_awaited_once()
        wf_kwargs = mock_workflow.call_args.kwargs
        assert wf_kwargs["upload_file_id"] == "fake-upload-id"

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_cv_upload_docx_success(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """DOCX upload → 200."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.return_value = FAKE_DIFY_OUTPUTS

        response = await client.post(CV_URL, headers=auth_headers, files=[_docx_file_tuple()])

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_cv_upload_json_string_outputs(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Dify returns sections as JSON strings → parser decodes them → 200."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.return_value = FAKE_DIFY_OUTPUTS_JSON_STRINGS

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)
        assert body["personalInfo"]["name"] == "Li Si"
        assert body["personalInfo"]["gender"] == "female"
        assert len(body["education"]["data"]) == 1

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_cv_upload_empty_sections(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Dify returns minimal/empty outputs → 200 with empty arrays and blank personal info."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.return_value = {
            "personalInfo": {},
            "education": [],
        }

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)
        assert body["personalInfo"]["name"] == ""
        assert body["personalInfo"]["gender"] == ""
        assert body["education"]["data"] == []
        assert body["academic"]["data"] == []  # missing key → empty

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_cv_upload_wrapped_in_result_key(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Dify wraps all fields under a 'result' key → parser unwraps → 200."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.return_value = FAKE_DIFY_OUTPUTS_WRAPPED

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)
        assert body["personalInfo"]["name"] == "Wang Wu"
        assert body["personalInfo"]["gender"] == "female"
        assert body["personalInfo"]["birthday"] == "2001-03-15"
        assert len(body["education"]["data"]) == 1
        assert body["education"]["data"][0]["name"] == "Fudan University"

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_cv_upload_wrapped_result_as_json_string(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Dify wraps fields under 'result' as a JSON string → parser decodes and unwraps → 200."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.return_value = FAKE_DIFY_OUTPUTS_WRAPPED_JSON_STRING

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)
        assert body["personalInfo"]["name"] == "Zhao Liu"
        assert body["personalInfo"]["gender"] == "male"

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_cv_upload_null_personal_info_fields(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Dify returns null for some personalInfo fields → converted to empty strings → 200."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.return_value = FAKE_DIFY_OUTPUTS_NULL_FIELDS

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 200
        body = response.json()
        assert_all_profile_200(body)
        assert body["personalInfo"]["name"] == "Test User"
        assert body["personalInfo"]["gender"] == ""  # null → ""
        assert body["personalInfo"]["birthday"] == ""  # null → ""


# ── 400: Bad Request ──────────────────────────────────────────────────────────

class TestCVUpload400:

    async def test_no_file_uploaded(self, client, mock_db, mock_redis, auth_headers):
        """POST with no file field → 400 'No file uploaded'."""
        _setup_redis_hit(mock_redis)

        response = await client.post(CV_URL, headers=auth_headers)

        assert response.status_code == 400
        assert_message_response(response.json(), "No file uploaded")

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_empty_file(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Upload a 0-byte PDF → 400 'Uploaded file is empty'."""
        _setup_redis_hit(mock_redis)

        response = await client.post(
            CV_URL,
            headers=auth_headers,
            files=[_pdf_file_tuple(content=b"")],
        )

        assert response.status_code == 400
        assert_message_response(response.json(), "Uploaded file is empty")
        mock_upload.assert_not_awaited()


# ── 401: Unauthorized ────────────────────────────────────────────────────────

class TestCVUpload401:

    async def test_missing_auth_header(self, client, mock_db, mock_redis):
        """No Authorization header → 422 (FastAPI validation) or 401."""
        response = await client.post(CV_URL, files=[_pdf_file_tuple()])
        # FastAPI returns 422 for missing required Header
        assert response.status_code == 422

    async def test_invalid_token(self, client, mock_db, mock_redis, auth_headers):
        """Token not found in Redis or DB → 401."""
        mock_redis.hgetall.return_value = {}  # cache miss
        # mock_db default: scalar_one_or_none returns None (no refresh token)

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 401
        assert_message_response(response.json(), "Invalid or expired token")


# ── 413: File Too Large ──────────────────────────────────────────────────────

class TestCVUpload413:

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_file_exceeds_10mb(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """File larger than 10 MB → 413."""
        _setup_redis_hit(mock_redis)
        large_content = b"x" * (10 * 1024 * 1024 + 1)  # 10 MB + 1 byte

        response = await client.post(
            CV_URL,
            headers=auth_headers,
            files=[_pdf_file_tuple(content=large_content)],
        )

        assert response.status_code == 413
        assert_message_response(response.json(), "File too large. Maximum size is 10 MB")
        mock_upload.assert_not_awaited()


# ── 415: Unsupported Media Type ──────────────────────────────────────────────

class TestCVUpload415:

    async def test_unsupported_txt_file(self, client, mock_db, mock_redis, auth_headers):
        """Upload a .txt file → 415."""
        _setup_redis_hit(mock_redis)

        response = await client.post(
            CV_URL,
            headers=auth_headers,
            files=[("file", ("resume.txt", b"plain text content", "text/plain"))],
        )

        assert response.status_code == 415
        assert_message_response(
            response.json(),
            "Unsupported file type. Only PDF and DOCX are allowed",
        )

    async def test_unsupported_image_file(self, client, mock_db, mock_redis, auth_headers):
        """Upload a .png image → 415."""
        _setup_redis_hit(mock_redis)

        response = await client.post(
            CV_URL,
            headers=auth_headers,
            files=[("file", ("photo.png", b"\x89PNG fake", "image/png"))],
        )

        assert response.status_code == 415
        assert_message_response(
            response.json(),
            "Unsupported file type. Only PDF and DOCX are allowed",
        )


# ── 422: Unprocessable Entity ────────────────────────────────────────────────

class TestCVUpload422:

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_dify_workflow_extraction_failure(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Dify workflow fails to extract data (status 422) → 422."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.side_effect = DifyUpstreamError(422, b"Workflow returned no structured output")

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 422
        assert_message_response(
            response.json(),
            "Failed to extract information from the uploaded file",
        )


# ── 502: Bad Gateway ────────────────────────────────────────────────────────

class TestCVUpload502:

    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_dify_file_upload_fails(
        self, mock_upload, client, mock_db, mock_redis, auth_headers
    ):
        """Dify file upload returns error → 502."""
        _setup_redis_hit(mock_redis)
        mock_upload.side_effect = DifyUpstreamError(502, b"Connection refused")

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 502
        assert_message_response(
            response.json(),
            "AI service is temporarily unavailable. Please try again later",
        )

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_dify_workflow_network_error(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Dify workflow call fails with network error → 502."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.side_effect = DifyUpstreamError(502, b"Timeout")

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 502
        assert_message_response(
            response.json(),
            "AI service is temporarily unavailable. Please try again later",
        )

    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_dify_api_key_not_configured(
        self, mock_upload, client, mock_db, mock_redis, auth_headers
    ):
        """Dify raises DifyUpstreamError(0, ...) when API key is missing → 502."""
        _setup_redis_hit(mock_redis)
        mock_upload.side_effect = DifyUpstreamError(0, b"DIFY_WORKFLOW_API_KEY is not set")

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 502
        assert_message_response(
            response.json(),
            "AI service is temporarily unavailable. Please try again later",
        )


# ── 500: Internal Server Error ──────────────────────────────────────────────

class TestCVUpload500:

    @patch("src.routers.profile.run_cv_parsing_workflow", new_callable=AsyncMock)
    @patch("src.routers.profile.upload_file_to_dify", new_callable=AsyncMock)
    async def test_unexpected_exception(
        self, mock_upload, mock_workflow, client, mock_db, mock_redis, auth_headers
    ):
        """Unexpected runtime error → 500."""
        _setup_redis_hit(mock_redis)
        mock_upload.return_value = "fake-upload-id"
        mock_workflow.side_effect = RuntimeError("Something went very wrong")

        response = await client.post(CV_URL, headers=auth_headers, files=[_pdf_file_tuple()])

        assert response.status_code == 500
        assert_message_response(response.json(), "Internal server error")
