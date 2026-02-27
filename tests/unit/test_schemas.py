"""
Unit tests for src/schemas/auth.py
Tests Pydantic schema validation rules (no DB/network required).
"""
import pytest
from pydantic import ValidationError
from src.schemas.auth import (
    SignUpRequest,
    ConfirmResetPasswordRequest,
    UpdateUserTypeRequest,
)


class TestSignUpRequestPassword:
    """Password strength validation on SignUpRequest."""

    def test_valid_password_is_accepted(self):
        """A password with letters and digits must pass validation."""
        req = SignUpRequest(name="Alice", email="alice@example.com", password="Password1")
        assert req.password == "Password1"

    def test_password_too_short_raises(self):
        """Password shorter than 8 characters must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SignUpRequest(name="Alice", email="alice@example.com", password="Ab1")
        errors = exc_info.value.errors()
        assert any("password" in str(e["loc"]) for e in errors)

    def test_password_no_digit_raises(self):
        """Password with only letters must raise ValidationError."""
        with pytest.raises(ValidationError):
            SignUpRequest(name="Alice", email="alice@example.com", password="OnlyLetters")

    def test_password_no_letter_raises(self):
        """Password with only digits must raise ValidationError."""
        with pytest.raises(ValidationError):
            SignUpRequest(name="Alice", email="alice@example.com", password="12345678")

    def test_password_exactly_8_chars_valid(self):
        """An 8-character password satisfying all rules must be accepted."""
        req = SignUpRequest(name="Alice", email="alice@example.com", password="Passw0rd")
        assert len(req.password) == 8


class TestSignUpRequestEmail:
    """Email normalisation on SignUpRequest."""

    def test_email_is_lowercased(self):
        """Mixed-case email must be stored as lowercase."""
        req = SignUpRequest(name="Bob", email="Bob.Smith@Example.COM", password="Password1")
        assert req.email == "bob.smith@example.com"

    def test_invalid_email_raises(self):
        """A string that is not a valid email must raise ValidationError."""
        with pytest.raises(ValidationError):
            SignUpRequest(name="Bob", email="not-an-email", password="Password1")


class TestConfirmResetPasswordRequest:
    """Password strength validation on ConfirmResetPasswordRequest."""

    def test_valid_new_password_accepted(self):
        """A strong new password must be accepted."""
        req = ConfirmResetPasswordRequest(code="123456", newPassword="NewPass1")
        assert req.new_password == "NewPass1"

    def test_new_password_too_short_raises(self):
        """A new password shorter than 8 characters must raise ValidationError."""
        with pytest.raises(ValidationError):
            ConfirmResetPasswordRequest(code="123456", newPassword="Ab1")

    def test_new_password_no_letter_raises(self):
        """A new password with only digits must raise ValidationError."""
        with pytest.raises(ValidationError):
            ConfirmResetPasswordRequest(code="123456", newPassword="12345678")

    def test_new_password_no_digit_raises(self):
        """A new password with only letters must raise ValidationError."""
        with pytest.raises(ValidationError):
            ConfirmResetPasswordRequest(code="123456", newPassword="OnlyLetters")

    def test_alias_field_works(self):
        """The 'newPassword' alias must populate the new_password field."""
        req = ConfirmResetPasswordRequest(**{"code": "654321", "newPassword": "Valid1Pass"})
        assert req.new_password == "Valid1Pass"


class TestUpdateUserTypeRequest:
    """user_type validation on UpdateUserTypeRequest."""

    @pytest.mark.parametrize("valid_type", [1, 2, 99])
    def test_valid_user_types_accepted(self, valid_type):
        """Values 1 (student), 2 (institution), and 99 (admin) must be accepted."""
        req = UpdateUserTypeRequest(user_type=valid_type)
        assert req.user_type == valid_type

    @pytest.mark.parametrize("invalid_type", [0, 3, 50, 100, -1])
    def test_invalid_user_types_raise(self, invalid_type):
        """Values outside the allowed set must raise ValidationError."""
        with pytest.raises(ValidationError):
            UpdateUserTypeRequest(user_type=invalid_type)
