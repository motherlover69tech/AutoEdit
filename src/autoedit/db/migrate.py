from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from autoedit.db.schema import cuts, metadata, project_cut_selections, projects, speaker_confirmations


def run_migrations(engine: Engine) -> None:
    """Create the Stage 3.1 schema.

    SQLAlchemy's `create_all` is idempotent and emits backend-specific DDL for the
    configured engine. This is intentionally small for the first stage; once the
    schema starts evolving, replace this with versioned Alembic migrations while
    preserving this public function for tests/deploy scripts.
    """
    metadata.create_all(engine)
    # ``create_all`` does not evolve an existing MySQL ENUM.  Keep the
    # versioned AI candidate kind available for existing installations while
    # leaving SQLite (whose enum is represented as a string) untouched.
    if engine.dialect.name == "mysql" and "cuts" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE cuts MODIFY kind "
                "ENUM('rough','ai','themed','social','manual') NOT NULL"
            ))
    if "speaker_confirmations" not in inspect(engine).get_table_names():
        speaker_confirmations.create(engine)
    if "project_cut_selections" not in inspect(engine).get_table_names():
        project_cut_selections.create(engine)
    with engine.begin() as connection:
        existing = {row[0] for row in connection.execute(project_cut_selections.select())}
        project_ids = connection.execute(projects.select().with_only_columns(projects.c.id)).all()
        for (project_id,) in project_ids:
            if project_id in existing:
                continue
            row = connection.execute(
                cuts.select().where(cuts.c.project_id == project_id, cuts.c.kind == "rough")
                .order_by(cuts.c.created_at.desc(), cuts.c.id.desc()).limit(1)
            ).first()
            if row is not None:
                connection.execute(project_cut_selections.insert().values(
                    project_id=project_id, cut_id=row._mapping["id"], selected_by="migration", version=1
                ))
