"""
Routers for Smart Document Chatbot Agent Service.
"""

from .health import router as health_router
from .chat import router as chat_router
from .hitl import router as hitl_router
from .a2a import router as a2a_router
from .mcp import router as mcp_router
from .actions import router as actions_router
from .memory import router as memory_router
from .admin import router as admin_router
from .training_jobs import router as training_jobs_router
from .documents import router as documents_router

__all__ = [
    "health_router",
    "chat_router",
    "hitl_router",
    "a2a_router",
    "mcp_router",
    "actions_router",
    "memory_router",
    "admin_router",
    "training_jobs_router",
    "documents_router",
]
