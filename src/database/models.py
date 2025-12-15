from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from src.database import Base


class Account(Base):
    """Account database model - User account table"""
    __tablename__ = "account"

    user_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)  # Hashed password
    user_type = Column(Integer, default=0)
    token = Column(String(500))
    user_name = Column(String(100))
    date_of_birth = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship to ClientGroup
    client_group = relationship("ClientGroup", back_populates="account", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Account(user_id={self.user_id}, email={self.email}, user_name={self.user_name})>"


class ClientGroup(Base):
    """Client Group database model - Client group table"""
    __tablename__ = "client_group"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('account.user_id', ondelete='CASCADE'), unique=True, nullable=False)
    user_profile = Column(JSONB)
    liked_university = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship to Account
    account = relationship("Account", back_populates="client_group")

    def __repr__(self):
        return f"<ClientGroup(id={self.id}, user_id={self.user_id})>"
