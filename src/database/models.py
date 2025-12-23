from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime, timezone
from .connection import Base


class User(Base):
    """User model for registered users"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_verified = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, name={self.name})>"


class SignUpVerification(Base):
    """Temporary storage for signup verification codes"""
    __tablename__ = "signup_verifications"

    id = Column(Integer, primary_key=True, index=True)
    temp_token = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    email = Column(String(255), index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    verification_code = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Verification link expiry

    def __repr__(self):
        return f"<SignUpVerification(email={self.email}, temp_token={self.temp_token})>"


class PasswordReset(Base):
    """Temporary storage for password reset tokens"""
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    temp_token = Column(String(255), unique=True, index=True, nullable=False)
    email = Column(String(255), index=True, nullable=False)
    reset_code = Column(String(10), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Reset link expiry

    def __repr__(self):
        return f"<PasswordReset(email={self.email}, temp_token={self.temp_token})>"
