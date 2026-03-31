# This code was completed by GRP Team 2025.11.
"""
Unit tests for src/utils/jwt_utils.py
Tests JWT creation/verification and helper token generators.
"""
import pytest
import jwt
from datetime import timedelta
from src.utils.jwt_utils import (
    create_access_token,
    verify_token,
    create_temp_token,
    generate_verification_code,
    SECRET_KEY,
    ALGORITHM,
)


class TestCreateAccessToken:
    def test_returns_string(self):
        """create_access_token must return a non-empty string."""
        token = create_access_token({"sub": "1"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_payload_is_embedded(self):
        """Decoded token must contain the original payload fields."""
        token = create_access_token({"sub": "42", "email": "user@example.com"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "42"
        assert payload["email"] == "user@example.com"

    def test_exp_claim_is_present(self):
        """Token must include an 'exp' claim."""
        token = create_access_token({"sub": "1"})
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_custom_expires_delta(self):
        """Custom expires_delta must be respected."""
        token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=5))
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload


class TestVerifyToken:
    def test_valid_token_returns_payload(self):
        """A freshly created token must decode to a dict with the expected fields."""
        token = create_access_token({"sub": "7", "role": "student"})
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "7"
        assert payload["role"] == "student"

    def test_expired_token_returns_none(self):
        """A token with a negative expiry must return None."""
        token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
        assert verify_token(token) is None

    def test_invalid_token_returns_none(self):
        """A random string must not decode and must return None."""
        assert verify_token("this.is.not.a.valid.jwt") is None

    def test_tampered_signature_returns_none(self):
        """A token whose signature is replaced must return None."""
        token = create_access_token({"sub": "1"})
        tampered = token[:-4] + "XXXX"
        assert verify_token(tampered) is None


class TestCreateTempToken:
    def test_returns_string(self):
        """create_temp_token must return a non-empty string."""
        token = create_temp_token()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_each_call_produces_unique_token(self):
        """Two consecutive calls must not return the same token."""
        tokens = {create_temp_token() for _ in range(20)}
        assert len(tokens) == 20


class TestGenerateVerificationCode:
    def test_default_length_is_six(self):
        """Default code length must be 6 characters."""
        code = generate_verification_code()
        assert len(code) == 6

    def test_custom_length(self):
        """Custom length parameter must be honoured."""
        code = generate_verification_code(length=8)
        assert len(code) == 8

    def test_code_is_all_digits(self):
        """Generated code must only contain digit characters."""
        for _ in range(20):
            code = generate_verification_code()
            assert code.isdigit()
