from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import update

import autoedit.api as api_module
from autoedit.db.schema import angles, projects
from tests.test_ai_cut_atomicity import _build_confirmed_ai_project


def test_terminal_confirmed_camera_and_wide_exhaustion_truncates_on_frame_boundary(
    tmp_path: Path, monkeypatch
):
    engine, client, project_id = _build_confirmed_ai_project(tmp_path)
    project_dir = tmp_path / project_id
    with engine.begin() as connection:
        rows = connection.execute(angles.select().where(angles.c.project_id == project_id)).all()
        by_role = {row._mapping["role"]: row._mapping["id"] for row in rows}
        connection.execute(
            update(angles).where(angles.c.project_id == project_id).values(duration_ms=671296)
        )
        connection.execute(
            update(angles).where(angles.c.id == by_role["cam_left"]).values(duration_ms=652720)
        )
        connection.execute(
            update(angles).where(angles.c.id == by_role["wide"]).values(duration_ms=666185)
        )
        connection.execute(
            update(projects).where(projects.c.id == project_id).values(fps_num=24, fps_den=1)
        )

    artifact_path = project_dir / "audio" / "ai" / "v1" / "result.json"
    artifact = json.loads(artifact_path.read_text())
    artifact["timeline_end_ms"] = 671296
    artifact_path.write_text(json.dumps(artifact))

    monkeypatch.setattr(
        api_module,
        "activity_from_turns",
        lambda *args, **kwargs: [
            {"start_ms": 0, "end_ms": 652720, "active": ["speaker-a"]},
            {"start_ms": 652720, "end_ms": 671296, "active": ["speaker-a"]},
        ],
    )
    monkeypatch.setattr(
        api_module,
        "generate_cdl",
        lambda *args, **kwargs: {
            "version": 1,
            "clips": [
                {"angle_id": by_role["cam_left"], "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 652708},
                {"angle_id": by_role["wide"], "timeline_in_ms": 652708, "src_in_ms": 652708, "dur_ms": 18588},
            ],
        },
    )

    response = client.post(f"/projects/{project_id}/cut", json={"analysis_source": "whisperx"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["truncation"] == {
        "applied": True,
        "reason_code": "terminal_authorized_camera_coverage_exhausted",
        "original_artifact_end_ms": 671296,
        "candidate_end_ms": 666167,
        "omitted_tail_duration_ms": 5129,
    }
    assert result["clips"][-1]["timeline_in_ms"] + result["clips"][-1]["dur_ms"] == 666167
    assert all(
        clip["timeline_in_ms"] + clip["dur_ms"] <= 666167 for clip in result["clips"]
    )
    published = json.loads(
        (project_dir / "audio" / "ai" / "v1" / "activity-whisperx.json").read_text()
    )
    assert published["truncation"] == result["truncation"]
