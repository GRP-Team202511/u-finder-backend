import uuid

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
    email_verified = Column(Boolean, nullable=False, default=False, comment="Whether the user's email has been verified")
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
        Index('ix_temp_token_verification_code_hashed', 'verification_code_hashed'),
        Index('ix_temp_token_token_type', 'token_type'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BigInteger, ForeignKey("account.user_id", ondelete="CASCADE"), nullable=False)
    token_hashed = Column(String(500), unique=True, nullable=False)
    token_type = Column(String(50), nullable=False, comment="e.g., email_verify, password_reset, email_change")
    verification_code_hashed = Column(String(255), nullable=True, comment="Hashed verification code for email/reset verification")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    expire_at = Column(DateTime(timezone=True), nullable=False)

    # Relationship
    account = relationship("Account", back_populates="temp_tokens")

    def __repr__(self):
        return f"<TempToken(id={self.id}, user_id={self.user_id}, token_type={self.token_type})>"


class UniversityProgram(Base):
    """Canonical university program entity — deduplicated and stable.

    Deduplication keys:
    - L1: normalized_url (UNIQUE) — official_program_url after normalization
    - L2: normalized_name — university name + program name + degree level, lowercased
    """
    __tablename__ = "university_program"
    __table_args__ = (
        Index('ix_university_program_normalized_url', 'normalized_url', unique=True),
        Index('ix_university_program_normalized_name', 'normalized_name'),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    normalized_url = Column(String(1000), nullable=True, unique=True, comment="L1 dedup key: normalized official_program_url")
    normalized_name = Column(String(1000), nullable=False, comment="L2 dedup key: normalized university+program+degree")
    program_data = Column(JSONB, nullable=False, comment="Full program card JSON from LLM")
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    liked_by = relationship("UserLikedUniversity", back_populates="university_program", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<UniversityProgram(id={self.id}, normalized_name={self.normalized_name})>"


class UserLikedUniversity(Base):
    """Association table: user <-> liked university program"""
    __tablename__ = "user_liked_university"
    __table_args__ = (
        Index('ix_user_liked_univ_user_program', 'user_id', 'university_program_id', unique=True),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("account.user_id", ondelete="CASCADE"), nullable=False)
    university_program_id = Column(String(36), ForeignKey("university_program.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    account = relationship("Account")
    university_program = relationship("UniversityProgram", back_populates="liked_by")

    def __repr__(self):
        return f"<UserLikedUniversity(user_id={self.user_id}, university_program_id={self.university_program_id})>"


class LlmUsageLog(Base):
    """Per-request LLM usage record for both chat and CV-parsing workflows."""
    __tablename__ = "llm_usage_log"
    __table_args__ = (
        Index('ix_llm_usage_log_source', 'source'),
        Index('ix_llm_usage_log_created_at', 'created_at'),
        Index('ix_llm_usage_log_user_id', 'user_id'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("account.user_id", ondelete="SET NULL"), nullable=True)
    source = Column(String(50), nullable=False, comment="'chat' or 'cv_parsing'")
    endpoint = Column(String(255), nullable=True, comment="Originating API route")
    prompt_tokens = Column(BigInteger, nullable=True)
    completion_tokens = Column(BigInteger, nullable=True)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    latency_seconds = Column(String(50), nullable=True, comment="Request latency in seconds")
    total_steps = Column(BigInteger, nullable=True, comment="Workflow total steps (cv_parsing only)")
    total_price = Column(String(50), nullable=True, comment="Cost reported by Dify")
    currency = Column(String(10), nullable=False, default="USD")
    dify_message_id = Column(String(255), nullable=True, comment="Dify message ID (chat only)")
    dify_conversation_id = Column(String(255), nullable=True, comment="Dify conversation ID (chat only)")
    dify_workflow_run_id = Column(String(255), nullable=True, comment="Dify workflow run ID (cv_parsing only)")
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    def __repr__(self):
        return f"<LlmUsageLog(id={self.id}, user_id={self.user_id}, source={self.source})>"

