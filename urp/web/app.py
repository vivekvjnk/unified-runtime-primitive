from contextlib import asynccontextmanager
from fastapi import FastAPI
from .routes import router, service
from urp.a2a.router import a2a_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes the default host agent on server startup and shuts down gracefully."""
    await service.initialize_agent("echo", "./agent_workspace")
    yield
    await service.shutdown()

def create_app() -> FastAPI:
    """FastAPI application factory for the URP Independent Hosting Framework."""
    app = FastAPI(
        title="URP Independent Hosting Framework (URP-HF)",
        description="Standalone web dashboard and REST/WebSocket API for hosting URP agents with native A2A protocol support.",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.include_router(a2a_router)
    return app

app = create_app()
