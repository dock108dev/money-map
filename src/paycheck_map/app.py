from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __product_version__
from .api import router
from .api_housing import router as housing_router
from .api_plaid import router as plaid_router
from .api_v2 import router as v2_router
from .config import settings
from .db import initialize_database
from .desktop_policy import uses_managed_data_home
from .local_security import LocalSecurityMiddleware, RequestFailureMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    if settings.desktop_mode and uses_managed_data_home(settings.desktop_data_mode):
        from .desktop_data_api import prepare_desktop_data_home

        prepare_desktop_data_home()
    else:
        settings.ensure_private_dirs()
        initialize_database()
    yield


app = FastAPI(
    title="Paycheck Map",
    version=__product_version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
    # Validation input/ctx/loc can contain rejected secrets or attacker-controlled field names.
    return JSONResponse(
        status_code=422,
        content={
            "detail": (
                "The request contains invalid or unsupported values. Review the entered fields."
            )
        },
        headers={"Cache-Control": "no-store"},
    )


app.add_middleware(RequestFailureMiddleware)
app.add_middleware(LocalSecurityMiddleware)
app.include_router(router)
app.include_router(v2_router)
app.include_router(housing_router)
app.include_router(plaid_router)
if settings.desktop_mode and uses_managed_data_home(settings.desktop_data_mode):
    from .desktop_data_api import router as desktop_data_router

    app.include_router(desktop_data_router)

web_dist = settings.web_dist_dir
assets = web_dist / "assets"
if assets.exists():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str) -> FileResponse:
    if path in {"api", "docs", "openapi.json", "redoc"} or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    index = web_dist / "index.html"
    if not index.exists():
        return FileResponse(Path(__file__).resolve().parent / "not_built.html", status_code=503)
    return FileResponse(index)
