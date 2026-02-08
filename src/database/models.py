from sqlalchemy import Column, BigInteger, String, DateTime, Boolean, SmallInteger, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy import text
from datetime import datetime, timezone
from .connection import Base


class Account(Base):
    """Account model - main user authentication table"""
    __tablename__ = "account"

    user_id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    user_name = Column(String(255), nullable=False, comment="User's display name")
    email = Column(String(255), unique=True, nullable=False, index=True, comment="Emails are all in small cases")
    password_hashed = Column(String(255), nullable=False)
    user_type = Column(SmallInteger, nullable=False)
    is_2fa_enabled = Column(Boolean, nullable=False, default=False)
    totp_secret_encrypted = Column(String, nullable=True, comment="use AES-GCM to encrypt, not null if 2FA is enabled")
    passkey_enabled = Column(Boolean, nullable=False, default=False)
    is_blocked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), comment="Auto-updated via trigger on UPDATE")

    # Relationships
    profile = relationship("UserProfile", back_populates="account", uselist=False, cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="account", cascade="all, delete-orphan")
    totp_backup_codes = relationship("TotpBackupCode", back_populates="account", cascade="all, delete-orphan")
    passkeys = relationship("Passkey", back_populates="account", cascade="all, delete-orphan")
    temp_tokens = relationship("TempToken", back_populates="account", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Account(user_id={self.user_id}, user_name={self.user_name}, email={self.email})>"


class UserProfile(Base):
    """User profile - stores detailed user information in JSONB format"""
    __tablename__ = "user_profile"

    user_id = Column(BigInteger, ForeignKey("account.user_id", ondelete="CASCADE"), primary_key=True, nullable=False)
    basic_info = Column(JSONB)
    education = Column(JSONB)
    academic = Column(JSONB)
    test = Column(JSONB)
    internship = Column(JSONB)
    project = Column(JSONB)
    campus = Column(JSONB)
    award = Column(JSONB)
    liked_university = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"), comment="Auto-updated via trigger on UPDATE")

    # Relationship
    account = relationship("Account", back_populates="profile")

    def __repr__(self):
        return f"<UserProfile(user_id={self.user_id})>"


class RefreshToken(Base):
    """Refresh token - used as session store to validate login state by token"""
    __tablename__ = "refresh_token"
    __table_args__ = (
        Index('ix_refresh_token_token_hashed', 'token_hashed', unique=True),
        Index('ix_refresh_token_user_id', 'user_id'),
        Index('ix_refresh_token_expire_at', 'expire_at'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("account.user_id", ondelete="CASCADE"), nullable=False)
    token_hashed = Column(String(500), nullable=False)
    user_agent = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    expire_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now() + interval '30 days'"))

    # Relationship
    account = relationship("Account", back_populates="refresh_tokens")

    def __repr__(self):
        return f"<RefreshToken(id={self.id}, user_id={self.user_id})>"


class TotpBackupCode(Base):
    """TOTP backup codes for 2FA recovery"""
    __tablename__ = "totp_backup_code"
    __table_args__ = (
        Index('ix_totp_backup_code_user_id_is_used', 'user_id', 'is_used'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("account.user_id", ondelete="CASCADE"), nullable=False)
    code_hashed = Column(String, nullable=False)
    is_used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    # Relationship
    account = relationship("Account", back_populates="totp_backup_codes")

    def __repr__(self):
        return f"<TotpBackupCode(id={self.id}, user_id={self.user_id}, is_used={self.is_used})>"


class Passkey(Base):
    """Passkey credentials for passwordless authentication"""
    __tablename__ = "passkey"
    __table_args__ = (
        Index('ix_passkey_user_id_credential_id', 'user_id', 'credential_id', unique=True),
        Index('ix_passkey_user_id_is_active', 'user_id', 'is_active'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("account.user_id", ondelete="CASCADE"), nullable=False)
    credential_id = Column(Text, unique=True, nullable=False)
    public_key = Column(Text, nullable=False)
    sign_count = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    last_used_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationship
    account = relationship("Account", back_populates="passkeys")

    def __repr__(self):
        return f"<Passkey(id={self.id}, user_id={self.user_id}, is_active={self.is_active})>"


class TempToken(Base):
    """Temporary tokens for email verification, password reset, etc."""
    __tablename__ = "temp_token"
    __table_args__ = (
        Index('ix_temp_token_user_id_expire_at', 'user_id', 'expire_at'),
        Index('ix_temp_token_token_hashed', 'token_hashed'),
        Index('ix_temp_token_token_type', 'token_type'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("account.user_id", ondelete="CASCADE"), nullable=False)
    token_hashed = Column(String(500), unique=True, nullable=False)
    token_type = Column(String(50), nullable=False, comment="e.g., email_verify, password_reset, email_change")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    expire_at = Column(DateTime(timezone=True), nullable=False)

    # Relationship
    account = relationship("Account", back_populates="temp_tokens")

    def __repr__(self):
        return f"<TempToken(id={self.id}, user_id={self.user_id}, token_type={self.token_type})>"

