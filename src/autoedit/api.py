from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Engine, create_engine

from autoedit.config import Settings
from autoedit.db.migrate import run_migrations
from autoedit.projects import create_project as create_project_record
from autoedit.projects import get_project as get_project_record


class ProjectCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    fps_num: int = Field(gt=0, strict=True)
    fps_den: int = Field(gt=0, strict=True)


def create_app(*, engine: Engine | None = None, data_root: str | Path | None = None) -> FastAPI:
    settings = Settings()
    app_engine = engine or create_engine(settings.sqlalchemy_url)
    app_data_root = Path(data_root) if data_root is not None else settings.data_root

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        run_migrations(app_engine)
        yield

    app = FastAPI(title="AUTOEDIT", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

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

    return app


app = create_app()
