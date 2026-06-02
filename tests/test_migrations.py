from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from autoedit.db.migrate import run_migrations
from autoedit.db.schema import projects


REQUIRED_TABLES = {
    "users",
    "projects",
    "angles",
    "audio_channels",
    "speaking_intervals",
    "transcript_segments",
    "topics",
    "topic_spans",
    "cuts",
    "notes",
    "jobs",
}


def test_migrations_create_all_required_tables_and_are_idempotent():
    engine = create_engine("sqlite:///:memory:")

    run_migrations(engine)
    run_migrations(engine)

    inspector = inspect(engine)
    assert REQUIRED_TABLES.issubset(set(inspector.get_table_names()))

    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    assert {
        "id",
        "name",
        "status",
        "fps_num",
        "fps_den",
        "timeline_origin_ms",
        "config_json",
        "created_at",
        "updated_at",
    }.issubset(project_columns)


def test_project_media_times_are_integer_columns():
    engine = create_engine("sqlite:///:memory:")
    run_migrations(engine)

    with Session(engine) as session:
        session.execute(
            projects.insert().values(
                id="01J00000000000000000000000",
                name="Interview",
                status="created",
                fps_num=24000,
                fps_den=1001,
                timeline_origin_ms=0,
                config_json={},
            )
        )
        session.commit()

    inspector = inspect(engine)
    timeline_column = next(
        column for column in inspector.get_columns("projects") if column["name"] == "timeline_origin_ms"
    )
    assert "INT" in str(timeline_column["type"]).upper()
