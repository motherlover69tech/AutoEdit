from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Engine, create_engine

from autoedit.auth import LoginRateLimiter, create_session_token, parse_session_token
from autoedit.config import Settings
from autoedit.db.migrate import run_migrations
from autoedit.projects import create_project as create_project_record
from autoedit.projects import get_project as get_project_record
from autoedit.uploads import UploadError, UploadNotFoundError
from autoedit.uploads import complete_upload as complete_upload_record
from autoedit.uploads import create_upload as create_upload_record
from autoedit.uploads import get_upload_status as get_upload_status_record
from autoedit.uploads import write_chunk as write_upload_chunk


class ProjectCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    fps_num: int = Field(gt=0, strict=True)
    fps_den: int = Field(gt=0, strict=True)


class LoginRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    password: Annotated[str, StringConstraints(min_length=1)]
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class UploadCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    filename: str
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    role: Literal["cam_left", "cam_right", "wide", "other"]
    total_bytes: int = Field(gt=0, strict=True)
    total_chunks: int = Field(gt=0, strict=True)


class UploadComplete(BaseModel):
    model_config = ConfigDict(strict=True)

    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
    total_bytes: int = Field(gt=0, strict=True)


def _public_origin(public_domain: str | None) -> str | None:
    if not public_domain:
        return None
    domain = public_domain.strip().rstrip("/")
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"


def _is_public_path(path: str) -> bool:
    return (
        path == "/health"
        or path == "/auth/login"
        or path.startswith("/.well-known/acme-challenge/")
    )


def create_app(
    *,
    engine: Engine | None = None,
    data_root: str | Path | None = None,
    auth_enabled: bool | None = None,
    operator_password: str | None = None,
    session_secret: str | None = None,
    public_domain: str | None = None,
    login_max_failures: int | None = None,
    login_lockout_seconds: int | None = None,
    session_cookie_name: str | None = None,
    session_cookie_secure: bool | None = None,
) -> FastAPI:
    settings = Settings()
    app_engine = engine or create_engine(settings.sqlalchemy_url)
    app_data_root = Path(data_root) if data_root is not None else settings.data_root

    app_auth_enabled = settings.auth_enabled if auth_enabled is None else auth_enabled
    app_operator_password = operator_password if operator_password is not None else settings.operator_password
    app_session_secret = session_secret if session_secret is not None else settings.session_secret
    app_public_domain = public_domain if public_domain is not None else settings.public_domain
    app_login_max_failures = (
        login_max_failures if login_max_failures is not None else settings.login_max_failures
    )
    app_login_lockout_seconds = (
        login_lockout_seconds
        if login_lockout_seconds is not None
        else settings.login_lockout_seconds
    )
    app_session_cookie_name = session_cookie_name or settings.session_cookie_name
    app_session_cookie_secure = (
        session_cookie_secure
        if session_cookie_secure is not None
        else settings.session_cookie_secure
    )
    allowed_origin = _public_origin(app_public_domain)
    login_limiter = LoginRateLimiter(
        max_failures=app_login_max_failures,
        lockout_seconds=app_login_lockout_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        run_migrations(app_engine)
        yield

    app = FastAPI(title="AUTOEDIT", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    @app.middleware("http")
    async def security_gate(request: Request, call_next):
        origin = request.headers.get("Origin")
        if allowed_origin and origin and origin != allowed_origin:
            return JSONResponse(status_code=403, content={"detail": "origin not allowed"})

        if app_auth_enabled and not _is_public_path(request.url.path):
            token = request.cookies.get(app_session_cookie_name)
            session = None
            if token and app_session_secret:
                session = parse_session_token(token, secret=app_session_secret)
            if session is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "authentication required"},
                )
            request.state.session = session

        return await call_next(request)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/auth/login", status_code=status.HTTP_204_NO_CONTENT)
    def login(payload: LoginRequest, request: Request) -> Response:
        client_key = request.client.host if request.client else "unknown"
        if not login_limiter.is_allowed(client_key):
            raise HTTPException(status_code=429, detail="too many failed login attempts")

        if not app_operator_password or not app_session_secret:
            raise HTTPException(status_code=503, detail="authentication is not configured")

        if not compare_digest(payload.password, app_operator_password):
            login_limiter.record_failure(client_key)
            raise HTTPException(status_code=401, detail="invalid credentials")

        login_limiter.record_success(client_key)
        token = create_session_token(
            display_name=payload.display_name,
            secret=app_session_secret,
        )
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.set_cookie(
            app_session_cookie_name,
            token,
            httponly=True,
            secure=app_session_cookie_secure,
            samesite="lax",
        )
        return response

    @app.get("/auth/me")
    def auth_me(request: Request) -> dict:
        return {"display_name": request.state.session["display_name"]}

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout() -> Response:
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(app_session_cookie_name)
        return response

    @app.post("/projects", status_code=status.HTTP_201_CREATED)
    def create_project(payload: ProjectCreate) -> dict:
        return create_project_record(
            app_engine,
            app_data_root,
            name=payload.name,
            fps_num=payload.fps_num,
            fps_den=payload.fps_den,
        )

    @app.get("/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return project

    @app.post("/projects/{project_id}/uploads", status_code=status.HTTP_201_CREATED)
    def create_upload(project_id: str, payload: UploadCreate) -> dict:
        try:
            return create_upload_record(
                app_engine,
                app_data_root,
                project_id=project_id,
                filename=payload.filename,
                label=payload.label,
                role=payload.role,
                total_bytes=payload.total_bytes,
                total_chunks=payload.total_chunks,
            )
        except UploadNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/upload/{upload_id}")
    def get_upload(upload_id: str) -> dict:
        try:
            return get_upload_status_record(app_data_root, upload_id)
        except UploadNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/upload/{upload_id}/chunk/{index}")
    async def upload_chunk(upload_id: str, index: int, request: Request) -> dict:
        try:
            return write_upload_chunk(app_data_root, upload_id, index, await request.body())
        except UploadNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/upload/{upload_id}/complete", status_code=status.HTTP_201_CREATED)
    def complete_upload(upload_id: str, payload: UploadComplete) -> dict:
        try:
            return complete_upload_record(
                app_engine,
                app_data_root,
                upload_id=upload_id,
                expected_sha256=payload.sha256.lower(),
                expected_total_bytes=payload.total_bytes,
            )
        except UploadNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
