from __future__ import annotations

from sqlalchemy import Engine

from autoedit.db.schema import metadata


def run_migrations(engine: Engine) -> None:
    """Create the Stage 3.1 schema.

    SQLAlchemy's `create_all` is idempotent and emits backend-specific DDL for the
    configured engine. This is intentionally small for the first stage; once the
    schema starts evolving, replace this with versioned Alembic migrations while
    preserving this public function for tests/deploy scripts.
    """
    metadata.create_all(engine)
