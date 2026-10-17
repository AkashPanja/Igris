from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, engine
from app.routers import auth as auth_router
from app.routers import connections as connections_router
from app.routers import setup as setup_router

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.services import scheduler

    task = scheduler.start()
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(setup_router.router, prefix="/api/setup", tags=["setup"])
    app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
    app.include_router(
        connections_router.router, prefix="/api/connections", tags=["connections"]
    )

    @app.get("/api/health")
    async def health() -> dict:
        from app.database import SessionLocal
        from app.services.auth import is_installed

        async with SessionLocal() as s:
            installed = await is_installed(s)
        return {"status": "ok", "version": "0.1.0", "installed": installed}

    if STATIC_DIR.exists():
        assets_dir = STATIC_DIR / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{path:path}")
        async def spa(path: str) -> FileResponse:
            target = STATIC_DIR / path
            if path and target.is_file():
                return FileResponse(target)
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
