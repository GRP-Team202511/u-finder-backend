"""
Routers module - Route management
"""
from src.routers.auth import router as auth_router
from src.routers.profile import router as profile_router
from src.routers.chat import router as chat_router

__all__ = ["auth_router", "profile_router", "chat_router"]