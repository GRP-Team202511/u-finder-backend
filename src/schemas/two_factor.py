"""
Two-Factor Authentication Pydantic schemas
"""
from pydantic import BaseModel
from typing import Optional


# ============ Setup 2FA ============
class Setup2FAResponse(BaseModel):
    totp_uri: str
    qr_code_base64: str
    backup_codes: list[str]


# ============ Confirm 2FA ============
class Confirm2FARequest(BaseModel):
    code: str


class Confirm2FAResponse(BaseModel):
    message: str


# ============ Verify 2FA (login) ============
class Verify2FARequest(BaseModel):
    code: str


class Verify2FAResponse(BaseModel):
    id: int
    name: str
    token: str


# ============ Disable 2FA ============
class Disable2FARequest(BaseModel):
    password: str


class Disable2FAResponse(BaseModel):
    message: str


# ============ Status ============
class TwoFAStatusResponse(BaseModel):
    is_2fa_enabled: bool
    backup_codes_remaining: int


# ============ Regenerate Backup Codes ============
class RegenerateBackupCodesRequest(BaseModel):
    code: str


class RegenerateBackupCodesResponse(BaseModel):
    backup_codes: list[str]
