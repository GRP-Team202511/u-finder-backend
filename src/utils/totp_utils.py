"""
TOTP utility functions for Two-Factor Authentication.

Handles TOTP secret generation, verification, QR code creation,
AES-256-GCM encryption/decryption, and backup code generation.
"""
import base64
import io
import os
import secrets

import pyotp
import qrcode
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config.settings import get_settings


def generate_totp_secret() -> str:
    """Generate a 32-character base32 TOTP secret."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    """Generate an otpauth:// URI for authenticator apps."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=email, issuer_name="U-Finder"
    )


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a TOTP code, allowing ±1 time window (30s tolerance)."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_qr_code_base64(uri: str) -> str:
    """Generate a QR code image as a data URI (base64 PNG)."""
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


def encrypt_secret(plaintext: str) -> str:
    """
    AES-256-GCM encrypt a TOTP secret.

    Returns base64(nonce ‖ ciphertext+tag).
    """
    key = base64.b64decode(get_settings().totp_encryption_key)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_secret(encrypted: str) -> str:
    """Decrypt an AES-256-GCM encrypted TOTP secret."""
    key = base64.b64decode(get_settings().totp_encryption_key)
    data = base64.b64decode(encrypted)
    nonce, ciphertext = data[:12], data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()


def generate_backup_codes(count: int = 8) -> list[str]:
    """Generate one-time backup recovery codes (8-char uppercase hex)."""
    return [secrets.token_hex(4).upper() for _ in range(count)]
