"""
Integration tests for User Profile / CV parsing Flow.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch, MagicMock
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import UniversityProgram

@pytest.mark.asyncio
async def test_workflow_05_profile_cv(integration_client: AsyncClient, real_db: AsyncSession):
    # 0. Setup dummy University Program
    dummy_unit_id = str(uuid.uuid4())
    dummy_prog = UniversityProgram(
        id=dummy_unit_id,
        normalized_name="mocked_university_mocked_program",
        program_data={"school": "Mocked U", "program": "Mocked P"}
    )
    real_db.add(dummy_prog)
    await real_db.commit()

    # 1. Signup and Login
    sent_codes = []
    async def mock_send_email(to_email, verification_code, **kwargs):
        sent_codes.append(verification_code)
        return True

    with patch("src.routers.auth.send_verification_email", side_effect=mock_send_email):
        res_signup = await integration_client.post("/auth/signup", json={
            "email": "profile_test@example.com",
            "name": "Profile Test",
            "password": "Password123"
        })
        assert res_signup.status_code == 200
        temp_token = res_signup.json().get("temp_token")
        
        await integration_client.post(
            "/auth/verify", 
            json={"code": sent_codes[0]}, 
            headers={"temp-token": temp_token}
        )

    res_login = await integration_client.post("/auth/login", json={
        "email": "profile_test@example.com",
        "password": "Password123"
    })
    token = res_login.json().get("token")

    # 2. Upload Profile CV with Mocks
    mock_upload = patch("src.routers.profile.upload_file_to_dify", return_value="fake_file_id")
    mock_parse = patch("src.routers.profile.run_cv_parsing_workflow", return_value={
        "personalInfo": {"name": "Mocked Name", "gender": "Male"},
        "education": [{"school": "Mocked University", "degree": "BSc"}],
        "academic": [], "test": [], "internship": [], "project": [], "campus": [], "award": []
    })

    with mock_upload, mock_parse:
        res_cv = await integration_client.post(
            "/profile/cv",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("test.pdf", b"fake pdf content", "application/pdf")}
        )
        assert res_cv.status_code == 200
        parsed_data = res_cv.json()
        assert parsed_data.get("personalInfo", {}).get("name") == "Mocked Name"

    # 3. Get updated profile
    res_get_profile = await integration_client.get(
        "/profile",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_get_profile.status_code == 200

    # 4. Check Liked Universities
    res_like = await integration_client.post(
        f"/profile/liked-university/{dummy_unit_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_like.status_code == 200

    res_get_likes = await integration_client.get(
        "/profile/liked-university",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_get_likes.status_code == 200
    likes_data = res_get_likes.json()
    likes_list = likes_data.get("data", []) if isinstance(likes_data, dict) else likes_data
    assert isinstance(likes_list, list)
    assert len(likes_list) > 0

    # 5. Delete liked university
    res_unlike = await integration_client.delete(
        f"/profile/liked-university/{dummy_unit_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_unlike.status_code == 200
