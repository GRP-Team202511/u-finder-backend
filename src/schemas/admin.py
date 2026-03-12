"""
<<<<<<< HEAD
Admin module Pydantic schemas.

Covers:
- POST /api/admin/auth/login   (request + response)
- GET  /api/admin/dashboard/summary (response)
"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


# ============ Auth ============

class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminLoginResponse(BaseModel):
    id: int
    name: str
    token: str


# ============ Shared ============

class ActionResult(BaseModel):
    result: str = "success"


# ============ Dashboard Summary — sub-models ============

class AdminUser(BaseModel):
    """Single row in the Recent Users table."""
    id: int
    name: str
    email: str
    type: str = Field(..., description="1 | 2 | 3 | 4")
    status: str = Field(..., description="active | pending | blocked")
    created_at: datetime
    available_actions: List[str] = Field(
        ..., description="Subset of [block, unblock, delete]"
    )


class LlmCostToday(BaseModel):
    """LLM Cost (Today) KPI card."""
    currency: str = "USD"
    amount: float = 0.0
    budget_per_day: Optional[float] = None


class LogEntry(BaseModel):
    """Single log entry in the System Logs Preview panel."""
    time: datetime
    level: str = Field(..., description="info | warn | error")
    message: str


class Money(BaseModel):
    currency: str = "USD"
    amount: float = 0.0


class ModelCostSnapshot(BaseModel):
    """Model Cost Snapshot panel."""
    total_requests: int = 0
    avg_latency_seconds: Optional[float] = None
    tokens_total: int = 0
    estimated_cost: Money = Field(default_factory=Money)


# ============ Dashboard Summary — top-level ============

class AdminDashboardSummary(BaseModel):
    """All-in-one dashboard payload returned by GET /api/admin/dashboard/summary."""
    total_users: int
    total_users_delta_week: Optional[int] = None
    llm_cost_today: LlmCostToday
    recent_users: List[AdminUser]
    recent_logs: List[LogEntry]
    model_cost_snapshot: ModelCostSnapshot
=======
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
>>>>>>> af4ac16ece60b04591957f0f6f4c1b88b8489f15
