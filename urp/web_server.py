"""
Backward compatibility bridge for urp.web_server.
Re-exports the FastAPI app from urp.web.
"""

from .web import app

__all__ = ["app"]
