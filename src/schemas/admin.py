"""
Admin schemas module
Pydantic models for admin endpoint requests and responses
"""
from datetime import datetime
from typing import List

from pydantic import BaseModel


class AdminUserResponse(BaseModel):
    """User record displayed in the Recent Users table."""
    id: int
    name: str
    email: str
    type: str
    status: str
    created_at: datetime
    available_actions: List[str]


class ErrorResponse(BaseModel):
    message: str
