"""
Utils module - Utility functions
"""
from .jwt_utils import (
    create_access_token,
    verify_token,
    create_temp_token,
    generate_verification_code,
    get_token_data,
    verify_user_from_db,
    verify_refresh_token_from_db,
)
from .password_utils import hash_password, verify_password, hash_token
from .cleanup import cleanup_all_expired_records, cleanup_expired_temp_tokens, cleanup_expired_refresh_tokens
from .email_utils import send_verification_email
from .session_utils import save_session, get_session, delete_session, delete_all_user_sessions
from .totp_utils import (
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
    generate_qr_code_base64,
    encrypt_secret,
    decrypt_secret,
    generate_backup_codes,
    check_totp_replay,
)

__all__ = [
    "create_access_token",
    "verify_token",
    "create_temp_token",
    "generate_verification_code",
    "get_token_data",
    "verify_user_from_db",
    "verify_refresh_token_from_db",
    "hash_password",
    "verify_password",
    "hash_token",
    "cleanup_all_expired_records",
    "cleanup_expired_temp_tokens",
    "cleanup_expired_refresh_tokens",
    "send_verification_email",
    "save_session",
    "get_session",
    "delete_session",
    "delete_all_user_sessions",
    "generate_totp_secret",
    "get_totp_uri",
    "verify_totp_code",
    "generate_qr_code_base64",
    "encrypt_secret",
    "decrypt_secret",
    "generate_backup_codes",
    "check_totp_replay",
]
