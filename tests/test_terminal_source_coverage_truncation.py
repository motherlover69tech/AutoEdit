from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.orm import Session

import autoedit.api as api_module
from autoedit.db.schema import angles, cuts, project_cut_selections, projects
from tests.test_ai_cut_atomicity import _build_confirmed_ai_project, _seed_prior_vad_cut


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

    _seed_prior_vad_cut(engine, tmp_path, project_id)
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

    evidence_paths = [
        project_dir / "audio" / "ai" / "v1" / "result.json",
        project_dir / "audio" / "ai" / "v1" / "word-timing-review.json",
        project_dir / "audio" / "program.m4a",
        project_dir / "audio" / "activity.json",
        project_dir / "audio" / "source-a.wav",
        project_dir / "audio" / "source-b.wav",
        project_dir / "edit" / "cdl.json",
    ]
    evidence_before = {path: path.read_bytes() for path in evidence_paths}
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
    candidate_path = project_dir / "edit" / "cdl_whisperx_run-one.json"
    assert json.loads(candidate_path.read_text())["truncation"] == result["truncation"]
    assert all(clip["angle_id"] != by_role["cam_right"] for clip in result["clips"])
    with Session(engine) as session:
        ai_row = session.execute(
            cuts.select().where(cuts.c.project_id == project_id, cuts.c.kind == "ai")
        ).one()
        selected = session.execute(
            project_cut_selections.select().where(project_cut_selections.c.project_id == project_id)
        ).all()
    assert ai_row._mapping["cdl_json"]["truncation"] == result["truncation"]
    assert not selected
    for path, original in evidence_before.items():
        assert path.read_bytes() == original, path
    assert result["clips"][-1]["timeline_in_ms"] + result["clips"][-1]["dur_ms"] == 666167
    assert all(
        clip["timeline_in_ms"] + clip["dur_ms"] <= 666167 for clip in result["clips"]
    )
    published = json.loads(
        (project_dir / "audio" / "ai" / "v1" / "activity-whisperx.json").read_text()
    )
    assert published["truncation"] == result["truncation"]


def _terminal_fixture(tmp_path: Path, monkeypatch, *, wide_end=666185, fps=(24, 1), artifact_end=671296):
    engine, client, project_id = _build_confirmed_ai_project(tmp_path)
    project_dir = tmp_path / project_id
    with engine.begin() as connection:
        rows = connection.execute(angles.select().where(angles.c.project_id == project_id)).all()
        by_role = {row._mapping["role"]: row._mapping["id"] for row in rows}
        connection.execute(update(angles).where(angles.c.project_id == project_id).values(duration_ms=artifact_end))
        connection.execute(update(angles).where(angles.c.id == by_role["cam_left"]).values(duration_ms=652720))
        connection.execute(update(angles).where(angles.c.id == by_role["wide"]).values(duration_ms=wide_end))
        connection.execute(update(projects).where(projects.c.id == project_id).values(fps_num=fps[0], fps_den=fps[1]))
    artifact_path = project_dir / "audio" / "ai" / "v1" / "result.json"
    artifact = json.loads(artifact_path.read_text())
    artifact["timeline_end_ms"] = artifact_end
    artifact_path.write_text(json.dumps(artifact))
    _seed_prior_vad_cut(engine, tmp_path, project_id)
    monkeypatch.setattr(api_module, "activity_from_turns", lambda *a, **k: [
        {"start_ms": 0, "end_ms": 652720, "active": ["speaker-a"]},
        {"start_ms": 652720, "end_ms": artifact_end, "active": ["speaker-a"]},
    ])
    monkeypatch.setattr(api_module, "generate_cdl", lambda *a, **k: {
        "version": 1,
        "clips": [
            {"angle_id": by_role["cam_left"], "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 652708},
            {"angle_id": by_role["wide"], "timeline_in_ms": 652708, "src_in_ms": 652708, "dur_ms": artifact_end - 652708},
        ],
    })
    return engine, client, project_id, project_dir, by_role


def test_internal_gap_is_fail_closed_without_publication(tmp_path: Path, monkeypatch):
    engine, client, pid, root, _roles = _terminal_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(api_module, "generate_cdl", lambda *a, **k: {
        "version": 1, "clips": [
            {"angle_id": _roles["cam_left"], "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 652708},
            {"angle_id": _roles["wide"], "timeline_in_ms": 652708, "src_in_ms": 652708, "dur_ms": 1000},
            {"angle_id": _roles["cam_right"], "timeline_in_ms": 653708, "src_in_ms": 653708, "dur_ms": 17588},
        ]})
    before = (root / "edit" / "cdl.json").read_bytes()
    response = client.post(f"/projects/{pid}/cut", json={"analysis_source": "whisperx"})
    assert response.status_code == 422
    assert (root / "edit" / "cdl.json").read_bytes() == before
    assert not list((root / "edit").glob("cdl_whisperx_*.json"))
    with Session(engine) as session:
        assert not session.execute(cuts.select().where(cuts.c.project_id == pid, cuts.c.kind == "ai")).all()


def test_exhausted_wide_with_unsafe_terminal_state_is_fail_closed(tmp_path: Path, monkeypatch):
    engine, client, pid, root, _roles = _terminal_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(api_module, "activity_from_turns", lambda *a, **k: [
        {"start_ms": 0, "end_ms": 652720, "active": ["speaker-a"]},
        {"start_ms": 652720, "end_ms": 671296, "active": ["speaker-a", "speaker-b"], "reason": "overlap:wide"},
    ])
    response = client.post(f"/projects/{pid}/cut", json={"analysis_source": "whisperx"})
    assert response.status_code == 422
    assert not list((root / "edit").glob("cdl_whisperx_*.json"))
    with Session(engine) as session:
        assert not session.execute(cuts.select().where(cuts.c.project_id == pid, cuts.c.kind == "ai")).all()


def test_full_length_wide_has_explicit_non_truncation_metadata(tmp_path: Path, monkeypatch):
    _engine, client, pid, _root, _roles = _terminal_fixture(
        tmp_path, monkeypatch, wide_end=671250, artifact_end=671250
    )
    result = client.post(f"/projects/{pid}/cut", json={"analysis_source": "whisperx"})
    assert result.status_code == 200, result.text
    assert result.json()["truncation"] == {
        "applied": False, "reason_code": None,
        "original_artifact_end_ms": 671250, "candidate_end_ms": 671250,
        "omitted_tail_duration_ms": 0,
    }


def test_exact_tail_determinism_excludes_candidate_identity(tmp_path: Path, monkeypatch):
    first = _terminal_fixture(tmp_path / "one", monkeypatch)
    first_result = first[1].post(f"/projects/{first[2]}/cut", json={"analysis_source": "whisperx"}).json()
    second = _terminal_fixture(tmp_path / "two", monkeypatch)
    second_result = second[1].post(f"/projects/{second[2]}/cut", json={"analysis_source": "whisperx"}).json()
    for result in (first_result, second_result):
        result.pop("project_id", None)
        result.pop("cut_id", None)
    assert first_result["truncation"] == second_result["truncation"]
    assert [(c["timeline_in_ms"], c["dur_ms"], c.get("reason_code")) for c in first_result["clips"]] == [(c["timeline_in_ms"], c["dur_ms"], c.get("reason_code")) for c in second_result["clips"]]
