from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from autoedit.api import create_app
from autoedit.config import Settings
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import angles, audio_channels, speaking_intervals, transcript_segments
from autoedit.projects import new_ulid


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    return engine


def _client(tmp_path: Path, **app_kwargs):
    engine = _engine()
    app = create_app(
        engine=engine,
        data_root=tmp_path,
        auth_enabled=False,
        **app_kwargs,
    )
    return TestClient(app), engine


def _project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={"name": "Hardening", "fps_num": 24000, "fps_den": 1001},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _upload_angle(client: TestClient, project_id: str, *, filename="a.mp4", label="A", content=b"media"):
    created = client.post(
        f"/projects/{project_id}/uploads",
        json={
            "filename": filename,
            "label": label,
            "role": "cam_left",
            "total_bytes": len(content),
            "total_chunks": 1,
        },
    )
    assert created.status_code == 201
    upload_id = created.json()["upload_id"]
    assert client.post(f"/upload/{upload_id}/chunk/0", content=content).status_code == 200
    complete = client.post(
        f"/upload/{upload_id}/complete",
        json={"sha256": hashlib.sha256(content).hexdigest(), "total_bytes": len(content)},
    )
    assert complete.status_code == 201
    return complete.json()


def _ffmpeg_ok(cmd, **kwargs):
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


def test_settings_sqlalchemy_url_uses_urlencoded_password():
    settings = Settings(
        DB_HOST="db.local",
        DB_PORT=3307,
        DB_NAME="autoedit_prod",
        DB_USER="auto edit",
        DB_PASSWORD="p@ ss/word",
    )

    assert settings.sqlalchemy_url == (
        "mysql+pymysql://auto+edit:p%40+ss%2Fword@db.local:3307/autoedit_prod"
    )
    assert "***" not in settings.sqlalchemy_url


def test_upload_chunk_rejects_oversized_body_before_write(tmp_path: Path):
    client, _ = _client(tmp_path, upload_max_chunk_bytes=4)
    project_id = _project(client)
    created = client.post(
        f"/projects/{project_id}/uploads",
        json={
            "filename": "a.mp4",
            "label": "A",
            "role": "cam_left",
            "total_bytes": 8,
            "total_chunks": 2,
        },
    )
    assert created.status_code == 201

    response = client.post(f"/upload/{created.json()['upload_id']}/chunk/0", content=b"12345")

    assert response.status_code == 413
    assert response.json()["detail"] == "upload chunk too large"


def test_proxy_filename_uses_angle_id_not_untrusted_label(tmp_path: Path):
    client, engine = _client(tmp_path)
    project_id = _project(client)
    angle = _upload_angle(client, project_id, label="../escape")

    with patch("autoedit.proxy.run_ffmpeg_watchdog", side_effect=_ffmpeg_ok):
        response = client.post(f"/projects/{project_id}/angles/{angle['id']}/proxy")

    assert response.status_code == 200
    assert response.json()["proxy_path"] == f"proxy/{angle['id']}.proxy.mp4"
    with Session(engine) as session:
        row = session.execute(select(angles).where(angles.c.id == angle["id"])).one()._mapping
    assert row.proxy_path == f"proxy/{angle['id']}.proxy.mp4"


def test_sync_wav_filename_uses_channel_id_not_untrusted_speaker_label(tmp_path: Path):
    client, engine = _client(tmp_path)
    project_id = _project(client)
    source_dir = tmp_path / project_id / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "a.mp4").write_bytes(b"")
    (source_dir / "b.mp4").write_bytes(b"")
    a1, a2 = new_ulid(), new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(id=a1, project_id=project_id, label="A", role="cam_left", source_path="source/a.mp4", sync_offset_ms=0))
        session.execute(angles.insert().values(id=a2, project_id=project_id, label="B", role="wide", source_path="source/b.mp4", sync_offset_ms=0))
        session.commit()
    mapped = client.post(
        f"/projects/{project_id}/channels",
        json={"mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "../bad"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "ok"},
        ]},
    )
    assert mapped.status_code == 201
    channel_ids = {ch["speaker_label"]: ch["id"] for ch in mapped.json()["channels"]}

    def sync_fn(guide_tracks, reference_angle_id, operator_nudge_ms=0):
        return {angle_id: 0 for angle_id in guide_tracks}

    app = create_app(engine=engine, data_root=tmp_path, auth_enabled=False, sync_fn=sync_fn)
    sync_client = TestClient(app)
    with patch("autoedit.audio.run_ffmpeg_watchdog", side_effect=_ffmpeg_ok):
        response = sync_client.post(f"/projects/{project_id}/sync")

    assert response.status_code == 200
    with Session(engine) as session:
        rows = session.execute(select(audio_channels).where(audio_channels.c.project_id == project_id)).all()
    wav_paths = {row.speaker_label: row.wav_path for row in rows}
    assert wav_paths["../bad"] == f"audio/ch_{channel_ids['../bad']}.wav"


def test_channel_remap_invalidates_dependent_analysis_rows(tmp_path: Path):
    client, engine = _client(tmp_path)
    project_id = _project(client)
    a1, a2 = new_ulid(), new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(id=a1, project_id=project_id, label="A", role="cam_left", source_path="source/a.mp4", sync_offset_ms=0))
        session.execute(angles.insert().values(id=a2, project_id=project_id, label="B", role="cam_right", source_path="source/b.mp4", sync_offset_ms=0))
        session.commit()
    first = client.post(
        f"/projects/{project_id}/channels",
        json={"mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "one"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "two"},
        ]},
    )
    assert first.status_code == 201
    old_channel_id = first.json()["channels"][0]["id"]
    with Session(engine) as session:
        session.execute(speaking_intervals.insert().values(channel_id=old_channel_id, start_ms=0, end_ms=100, mean_db=-10, peak_db=-5))
        session.execute(transcript_segments.insert().values(project_id=project_id, channel_id=old_channel_id, start_ms=0, end_ms=100, text="hello", words_json=[]))
        session.commit()

    remap = client.post(
        f"/projects/{project_id}/channels",
        json={"mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "new-one"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "new-two"},
        ]},
    )

    assert remap.status_code == 201
    with Session(engine) as session:
        assert session.execute(select(func.count()).select_from(speaking_intervals)).scalar_one() == 0
        assert session.execute(select(func.count()).select_from(transcript_segments)).scalar_one() == 0


def test_program_audio_passes_map_as_separate_ffmpeg_argv_tokens():
    from autoedit.program_audio import generate_program_audio

    captured = []
    def capture(cmd, **kwargs):
        captured.append(cmd)
        return _ffmpeg_ok(cmd, **kwargs)

    with patch("autoedit.program_audio.run_ffmpeg_watchdog", side_effect=capture):
        generate_program_audio([("/tmp/a.wav", 0), ("/tmp/b.wav", 50)], "/tmp/out.m4a")

    cmd = captured[0]
    assert "-map" in cmd
    map_index = cmd.index("-map")
    assert cmd[map_index + 1] == "[out]"
    assert not any(str(part).startswith("-map ") for part in cmd)


def test_media_endpoint_only_serves_db_known_media_with_playback_headers(tmp_path: Path):
    client, engine = _client(tmp_path)
    project_id = _project(client)
    proxy_dir = tmp_path / project_id / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    known = f"{new_ulid()}.proxy.mp4"
    (proxy_dir / known).write_bytes(b"known")
    (proxy_dir / "internal.proxy.mp4").write_bytes(b"internal")
    angle_id = new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(
            id=angle_id,
            project_id=project_id,
            label="A",
            role="cam_left",
            source_path="source/a.mp4",
            proxy_path=f"proxy/{known}",
            sync_offset_ms=0,
        ))
        session.commit()

    unknown_response = client.get(f"/projects/{project_id}/media/proxy/internal.proxy.mp4")
    known_response = client.get(f"/projects/{project_id}/media/proxy/{known}")

    assert unknown_response.status_code == 404
    assert known_response.status_code == 200
    assert known_response.headers["content-type"].startswith("video/mp4")
    assert "attachment" not in known_response.headers.get("content-disposition", "").lower()


def test_sync_uses_wide_angle_as_reference_when_present(tmp_path: Path):
    client, engine = _client(tmp_path)
    project_id = _project(client)
    source_dir = tmp_path / project_id / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "cam.mp4").write_bytes(b"")
    (source_dir / "wide.mp4").write_bytes(b"")
    cam_id, wide_id = new_ulid(), new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(id=cam_id, project_id=project_id, label="Cam", role="cam_left", source_path="source/cam.mp4", sync_offset_ms=0))
        session.execute(angles.insert().values(id=wide_id, project_id=project_id, label="Wide", role="wide", source_path="source/wide.mp4", sync_offset_ms=0))
        session.commit()
    assert client.post(
        f"/projects/{project_id}/channels",
        json={"mappings": [
            {"source_angle_id": cam_id, "channel_index": 0, "speaker_label": "cam"},
            {"source_angle_id": wide_id, "channel_index": 0, "speaker_label": "wide"},
        ]},
    ).status_code == 201
    references = []
    def sync_fn(guide_tracks, reference_angle_id, operator_nudge_ms=0):
        references.append(reference_angle_id)
        return {angle_id: (0 if angle_id == reference_angle_id else 10) for angle_id in guide_tracks}
    app = create_app(engine=engine, data_root=tmp_path, auth_enabled=False, sync_fn=sync_fn)
    sync_client = TestClient(app)

    with patch("autoedit.audio.run_ffmpeg_watchdog", side_effect=_ffmpeg_ok):
        response = sync_client.post(f"/projects/{project_id}/sync")

    assert response.status_code == 200
    assert references == [wide_id]


def test_diarize_response_marks_placeholder_mode(tmp_path: Path):
    client, engine = _client(tmp_path)
    project_id = _project(client)
    a1, a2 = new_ulid(), new_ulid()
    with Session(engine) as session:
        session.execute(angles.insert().values(id=a1, project_id=project_id, label="A", role="cam_left", source_path="source/a.mp4", sync_offset_ms=0))
        session.execute(angles.insert().values(id=a2, project_id=project_id, label="B", role="cam_right", source_path="source/b.mp4", sync_offset_ms=0))
        session.commit()
    assert client.post(
        f"/projects/{project_id}/channels",
        json={"mappings": [
            {"source_angle_id": a1, "channel_index": 0, "speaker_label": "presenter"},
            {"source_angle_id": a2, "channel_index": 0, "speaker_label": "interviewee"},
        ]},
    ).status_code == 201

    response = client.post(f"/projects/{project_id}/diarize")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "channel_mapping_placeholder"
    assert body["is_mock"] is True
