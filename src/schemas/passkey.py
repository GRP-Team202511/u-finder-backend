"""
Passkey (WebAuthn/FIDO2) related Pydantic models
"""
from typing import Any

from pydantic import BaseModel, EmailStr, Field


# ============ Register Options ============
class PasskeyRegisterOptionsResponse(BaseModel):
    options: dict[str, Any] = Field(
        ...,
        description="WebAuthn PublicKeyCredentialCreationOptions (JSON-serialized).",
    )


# ============ Register Verify ============
class PasskeyRegisterVerifyRequest(BaseModel):
    credential: dict[str, Any] = Field(
        ...,
        description=(
            "PublicKeyCredential returned by navigator.credentials.create(), "
            "JSON-serialized with base64url-encoded binary fields."
        ),
    )


class PasskeyRegisterVerifyResponse(BaseModel):
    message: str


# ============ Login Options ============
class PasskeyLoginOptionsRequest(BaseModel):
    email: EmailStr


class PasskeyLoginOptionsResponse(BaseModel):
    options: dict[str, Any] = Field(
        ...,
        description="WebAuthn PublicKeyCredentialRequestOptions (JSON-serialized).",
    )


# ============ Login Verify ============
class PasskeyLoginVerifyRequest(BaseModel):
    email: EmailStr
    credential: dict[str, Any] = Field(
        ...,
        description=(
            "PublicKeyCredential returned by navigator.credentials.get(), "
            "JSON-serialized with base64url-encoded binary fields."
        ),
    )


class PasskeyLoginVerifyResponse(BaseModel):
    id: int
    name: str
    token: str


# ============ Error ============
class PasskeyErrorResponse(BaseModel):
    message: str
