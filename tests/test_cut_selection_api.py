"""Contract coverage for explicit cut sources and durable cut selection."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, cuts, project_cut_selections
from autoedit.projects import new_ulid


@pytest.fixture
def cut_api(tmp_path: Path):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine)
    client = TestClient(create_app(engine=engine, data_root=tmp_path, auth_enabled=False))
    project = client.post("/projects", json={"name": "selection", "fps_num": 25, "fps_den": 1}).json()
    project_id = project["id"]
    left, wide = new_ulid(), new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert(), [
            {"id": left, "project_id": project_id, "label": "Left", "role": "cam_left",
             "source_path": "source/left.mp4", "proxy_path": "proxy/left.mp4", "duration_ms": 5000},
            {"id": wide, "project_id": project_id, "label": "Wide", "role": "wide",
             "source_path": "source/wide.mp4", "proxy_path": "proxy/wide.mp4", "duration_ms": 5000},
        ])
        session.commit()
    audio = tmp_path / project_id / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    (audio / "program.m4a").write_bytes(b"program")
    proxy_dir = tmp_path / project_id / "proxy"
    proxy_dir.mkdir(exist_ok=True)
    (proxy_dir / "left.mp4").write_bytes(b"proxy")
    (proxy_dir / "wide.mp4").write_bytes(b"proxy")
    (audio / "activity.json").write_text(json.dumps({
        "timeline": [{"start_ms": 0, "end_ms": 5000, "active": []}],
        "total_duration_ms": 5000,
    }))
    # Presence alone must not make an AI artifact authoritative for VAD.
    ai_dir = audio / "ai" / "v1"
    ai_dir.mkdir(parents=True)
    (ai_dir / "result.json").write_text(json.dumps({"not": "a valid artifact"}))
    summary_dir = tmp_path / project_id / "transcript"
    summary_dir.mkdir(exist_ok=True)
    (summary_dir / "summary.json").write_text(json.dumps({"topics": []}))
    return client, engine, tmp_path, project_id, left, wide


def _generate(client: TestClient, project_id: str, **payload) -> dict:
    response = client.post(f"/projects/{project_id}/cut", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_vad_source_is_explicit_and_initially_selected(cut_api):
    client, engine, root, project_id, _left, _wide = cut_api
    candidate = _generate(client, project_id, analysis_source="vad")
    assert candidate["analysis_source"] == "vad"
    assert candidate["selected"] is True
    assert candidate["selection_version"] == 1
    assert json.loads((root / project_id / "edit" / "cdl.json").read_text())["analysis_source"] == "vad"
    with Session(engine) as session:
        selection = session.execute(project_cut_selections.select()).one()._mapping
        assert selection["cut_id"] == candidate["cut_id"]


def test_vad_does_not_inspect_or_fallback_to_present_ai_artifact(cut_api):
    client, _engine, _root, project_id, _left, _wide = cut_api
    candidate = _generate(client, project_id)
    assert candidate["analysis_source"] == "vad"
    assert candidate["cut_id"]


def test_whisperx_failure_preserves_selected_vad(cut_api):
    client, engine, root, project_id, _left, _wide = cut_api
    prior = _generate(client, project_id)
    prior_mirror = (root / project_id / "edit" / "cdl.json").read_bytes()
    response = client.post(f"/projects/{project_id}/cut", json={"analysis_source": "whisperx"})
    assert response.status_code in (409, 422)
    assert (root / project_id / "edit" / "cdl.json").read_bytes() == prior_mirror
    with Session(engine) as session:
        selection = session.execute(project_cut_selections.select()).one()._mapping
        assert selection["cut_id"] == prior["cut_id"]


def test_generation_is_immutable_and_list_marks_only_selected(cut_api):
    client, engine, _root, project_id, _left, _wide = cut_api
    first = _generate(client, project_id)
    second = _generate(client, project_id, name="second")
    assert second["cut_id"] != first["cut_id"]
    assert second["selected"] is False
    listing = client.get(f"/projects/{project_id}/cuts")
    assert listing.status_code == 200
    rows = {row["cut_id"]: row for row in listing.json()["cuts"]}
    assert rows[first["cut_id"]]["is_selected"] is True
    assert rows[second["cut_id"]]["is_selected"] is False
    with Session(engine) as session:
        assert session.execute(project_cut_selections.select()).one()._mapping["cut_id"] == first["cut_id"]


def test_selection_save_is_versioned_and_idempotent(cut_api):
    client, _engine, root, project_id, _left, _wide = cut_api
    first = _generate(client, project_id)
    second = _generate(client, project_id, name="second")
    saved = client.put(f"/projects/{project_id}/cut-selection", json={
        "cut_id": second["cut_id"], "expected_version": 1,
    })
    assert saved.status_code == 200
    assert saved.json()["version"] == 2
    mirror = json.loads((root / project_id / "edit" / "cdl.json").read_text())
    assert mirror["analysis_source"] == "vad"
    assert mirror["clips"] == second["clips"]
    repeat = client.put(f"/projects/{project_id}/cut-selection", json={
        "cut_id": second["cut_id"], "expected_version": 2,
    })
    assert repeat.status_code == 200
    assert repeat.json()["version"] == 2
    stale = client.put(f"/projects/{project_id}/cut-selection", json={
        "cut_id": first["cut_id"], "expected_version": 1,
    })
    assert stale.status_code == 409


def test_selection_rejects_cross_project_cut(cut_api):
    client, engine, _root, project_id, _left, _wide = cut_api
    first = _generate(client, project_id)
    other = client.post("/projects", json={"name": "other", "fps_num": 25, "fps_den": 1}).json()["id"]
    other_cut = new_ulid()
    with Session(engine) as session:
        session.execute(cuts.insert().values(
            id=other_cut, project_id=other, name="other", kind="rough", params_json={},
            cdl_json={"version": 1, "clips": [{"angle_id": "x", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 1000}]},
        ))
        session.commit()
    response = client.put(f"/projects/{project_id}/cut-selection", json={
        "cut_id": other_cut, "expected_version": 1,
    })
    assert response.status_code == 400
    assert client.get(f"/projects/{project_id}/cuts").json()["selection_version"] == 1
    assert first["cut_id"]


def test_selection_rejects_invalid_cdl(cut_api):
    client, engine, _root, project_id, _left, _wide = cut_api
    first = _generate(client, project_id)
    invalid = new_ulid()
    with Session(engine) as session:
        session.execute(cuts.insert().values(
            id=invalid, project_id=project_id, name="bad", kind="rough", params_json={},
            cdl_json={"clips": [{"malformed": True}], "analysis_source": "vad"},
        ))
        session.commit()
    response = client.put(f"/projects/{project_id}/cut-selection", json={
        "cut_id": invalid, "expected_version": 1,
    })
    assert response.status_code == 422
    assert client.get(f"/projects/{project_id}/cuts").json()["selection_version"] == 1
    assert first["selected"] is True


def test_selection_mirror_failure_rolls_back_selection(cut_api, monkeypatch: pytest.MonkeyPatch):
    client, engine, root, project_id, _left, _wide = cut_api
    first = _generate(client, project_id)
    second = _generate(client, project_id, name="second")
    mirror = root / project_id / "edit" / "cdl.json"
    prior_bytes = mirror.read_bytes()
    original_replace = Path.replace

    def fail_mirror_replace(path: Path, target: Path):
        if target.name == "cdl.json":
            raise OSError("simulated mirror failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_mirror_replace)
    response = TestClient(client.app, raise_server_exceptions=False).put(
        f"/projects/{project_id}/cut-selection",
        json={"cut_id": second["cut_id"], "expected_version": 1},
    )
    assert response.status_code == 500
    assert mirror.read_bytes() == prior_bytes
    with Session(engine) as session:
        selection = session.execute(project_cut_selections.select()).one()._mapping
        assert selection["cut_id"] == first["cut_id"]
        assert selection["version"] == 1


def test_migration_backfills_latest_rough_cut(cut_api):
    client, engine, _root, project_id, _left, _wide = cut_api
    candidate = _generate(client, project_id)
    with engine.begin() as connection:
        connection.execute(project_cut_selections.delete())
    run_migrations(engine)
    with Session(engine) as session:
        selection = session.execute(project_cut_selections.select()).one()._mapping
        assert selection["cut_id"] == candidate["cut_id"]
        assert selection["selected_by"] == "migration"


def test_legacy_resolver_row_without_selection_version_is_safe(cut_api):
    client, engine, _root, project_id, _left, _wide = cut_api
    cut_id = new_ulid()
    with Session(engine) as session:
        session.execute(cuts.insert().values(
            id=cut_id, project_id=project_id, name="legacy", kind="rough", params_json={},
            cdl_json={"version": 1, "clips": []},
        ))
        session.commit()
    listing = client.get(f"/projects/{project_id}/cuts")
    assert listing.status_code == 200
    assert listing.json()["selection_version"] is None


def test_all_consumers_stay_on_selected_cut_after_unsaved_candidate(cut_api):
    client, _engine, _root, project_id, _left, _wide = cut_api
    selected = _generate(client, project_id, name="selected")
    (_root / project_id / "audio" / "ai" / "v1" / "result.json").unlink()
    player_response = client.get(f"/projects/{project_id}/player-state")
    assert player_response.status_code == 200, player_response.text
    before = {
        "player": player_response.json()["cut"],
        "timeline": client.get(f"/projects/{project_id}/timeline-state").json(),
        "review": client.post(f"/projects/{project_id}/cut/review").json(),
        "export": client.post(f"/projects/{project_id}/export").json(),
    }
    candidate = _generate(client, project_id, name="preview-only")
    assert candidate["selected"] is False
    reloaded = TestClient(client.app)
    after = {
        "player": reloaded.get(f"/projects/{project_id}/player-state").json()["cut"],
        "timeline": reloaded.get(f"/projects/{project_id}/timeline-state").json(),
        "review": reloaded.post(f"/projects/{project_id}/cut/review").json(),
        "export": reloaded.post(f"/projects/{project_id}/export").json(),
    }
    assert before["player"]["id"] == selected["cut_id"]
    assert before["timeline"]["selected_cut_id"] == selected["cut_id"]
    assert before["review"]["cut_id"] == selected["cut_id"]
    assert before["export"]["cut_id"] == selected["cut_id"]
    assert after["player"] == before["player"]
    assert after["timeline"]["selected_cut_id"] == before["timeline"]["selected_cut_id"]
    assert after["review"]["cut_id"] == before["review"]["cut_id"]
    assert after["export"]["cut_id"] == before["export"]["cut_id"]