"""
Unit tests for src/utils/password_utils.py
Tests password hashing, verification, and token hashing.
"""
import pytest
from src.utils.password_utils import hash_password, verify_password, hash_token


class TestHashPassword:
    def test_hash_differs_from_plain(self):
        """Hashed password must not equal the plain-text input."""
        plain = "Password123"
        hashed = hash_password(plain)
        assert hashed != plain

    def test_hash_is_string(self):
        """hash_password must return a string."""
        result = hash_password("Password123")
        assert isinstance(result, str)

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt salts each hash, so two calls must produce different digests."""
        plain = "Password123"
        assert hash_password(plain) != hash_password(plain)


class TestVerifyPassword:
    def test_correct_password_returns_true(self):
        """verify_password must return True for the matching plain-text."""
        plain = "Password123"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_wrong_password_returns_false(self):
        """verify_password must return False for a non-matching plain-text."""
        hashed = hash_password("Password123")
        assert verify_password("WrongPassword1", hashed) is False

    def test_empty_string_returns_false(self):
        """An empty string must not match a real password hash."""
        hashed = hash_password("Password123")
        assert verify_password("", hashed) is False


class TestHashToken:
    def test_is_deterministic(self):
        """Same token must always produce the same HMAC-SHA256 digest."""
        token = "some-random-token"
        assert hash_token(token) == hash_token(token)

    def test_different_tokens_produce_different_hashes(self):
        """Different tokens must not collide."""
        assert hash_token("token-a") != hash_token("token-b")

    def test_returns_64_char_hex_string(self):
        """SHA-256 hex digest is always 64 lowercase hex characters."""
        result = hash_token("any-token")
        assert isinstance(result, str)
        assert len(result) == 64
        assert result == result.lower()
        int(result, 16)  # raises ValueError if not valid hex
