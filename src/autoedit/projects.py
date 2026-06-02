from __future__ import annotations

import json
from pathlib import Path
import secrets
import time

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from autoedit.db.schema import projects
from autoedit.project_paths import create_project_tree

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """Generate a 26-character ULID string without external dependencies."""
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def public_project(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "fps_num": row.fps_num,
        "fps_den": row.fps_den,
        "timeline_origin_ms": row.timeline_origin_ms,
        "config_json": row.config_json or {},
    }


def _write_manifest(project_dir: Path, manifest: dict) -> None:
    tmp_path = project_dir / "project.json.tmp"
    final_path = project_dir / "project.json"
    tmp_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(final_path)


def create_project(
    engine: Engine,
    data_root: str | Path,
    *,
    name: str,
    fps_num: int,
    fps_den: int,
) -> dict:
    project_id = new_ulid()
    project_dir = create_project_tree(data_root, project_id)

    with Session(engine) as session:
        session.execute(
            projects.insert().values(
                id=project_id,
                name=name,
                status="created",
                fps_num=fps_num,
                fps_den=fps_den,
                timeline_origin_ms=0,
                config_json={},
            )
        )
        session.commit()
        row = session.execute(select(projects).where(projects.c.id == project_id)).one()._mapping

    manifest = public_project(row)
    _write_manifest(project_dir, manifest)
    return manifest


def get_project(engine: Engine, project_id: str) -> dict | None:
    with Session(engine) as session:
        row = session.execute(select(projects).where(projects.c.id == project_id)).one_or_none()
        if row is None:
            return None
        return public_project(row._mapping)
