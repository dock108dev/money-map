from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __product_version__
from .api import router
from .config import settings
from .db import initialize_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    if settings.desktop_mode and settings.desktop_data_mode in {
        "production-v1",
        "acceptance-synthetic-v1",
        "keychain-acceptance-v1",
    }:
        from .desktop_data_api import prepare_desktop_data_home

        prepare_desktop_data_home()
    else:
        settings.ensure_private_dirs()
        initialize_database()
    yield


app = FastAPI(
    title="Paycheck Map",
    version=__product_version__,
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.include_router(router)
if settings.desktop_mode and settings.desktop_data_mode in {
    "production-v1",
    "acceptance-synthetic-v1",
    "keychain-acceptance-v1",
}:
    from .desktop_data_api import router as desktop_data_router

    app.include_router(desktop_data_router)

web_dist = settings.web_dist_dir
assets = web_dist / "assets"
if assets.exists():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str) -> FileResponse:
    del path
    index = web_dist / "index.html"
    if not index.exists():
        return FileResponse(Path(__file__).resolve().parent / "not_built.html", status_code=503)
    return FileResponse(index)
