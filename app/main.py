from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import router as auth_router
from app.config import Settings
from app.db import reset_admin_password, setup_storage
from app.drive import router as drive_router
from app.sources import configured_sources, router as sources_router
from app.views import STATIC_DIR


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    if not config.username:
        raise RuntimeError("ADMIN_USERNAME no puede estar vacío.")
    configured_sources(config)
    setup_storage(config)
    application = FastAPI(title="Mi Drive", docs_url=None, redoc_url=None)
    application.state.settings = config
    application.add_middleware(
        SessionMiddleware, secret_key=config.session_secret, same_site="lax", https_only=False
    )
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.include_router(auth_router)
    application.include_router(drive_router)
    application.include_router(sources_router)
    return application
