# This code was completed by GRP Team 2025.11.
"""
Routers module - Route management
"""
from src.routers.auth import router as auth_router
from src.routers.profile import router as profile_router
from src.routers.chat import router as chat_router
from src.routers.two_factor import router as two_factor_router
from src.routers.admin import router as admin_router
from src.routers.passkey import router as passkey_router

__all__ = [
    "auth_router",
    "profile_router",
    "chat_router",
    "two_factor_router",
    "admin_router",
    "passkey_router",
]