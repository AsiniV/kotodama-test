"""
FastAPI application factory and main entry point.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from backend.core.config import get_settings
from backend.db.session import init_db, close_db

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("kotodama")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown events."""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await close_db()
    logger.info("Database connections closed")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Modular Multi-Agent Game Generation Service on Godot",
        lifespan=lifespan,
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure properly in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Internal server error: {str(exc)}"},
        )
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": settings.app_version}
    
    # Root endpoint
    @app.get("/")
    async def root():
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "description": "Modular Multi-Agent Game Generation Service on Godot",
            "docs": "/docs",
        }
    
    # Register API routers (Phase 3 - UI/UX)
    from backend.api import generation, lore
    
    app.include_router(generation.router, prefix="/api/v1/generation", tags=["generation"])
    app.include_router(lore.router, prefix="/api/v1/lore", tags=["lore"])
    
    # Register Phase 9 routers (Export + Marketplace)
    from backend.api import marketplace, export
    
    app.include_router(marketplace.router, prefix="/api/v1/marketplace", tags=["marketplace"])
    app.include_router(export.router, prefix="/api/v1/export", tags=["export"])
    
    logger.info("API routers registered (including Phase 9: Export + Marketplace)")
    
    logger.info("Application created successfully")
    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
