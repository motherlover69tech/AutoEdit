from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import mimetypes
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Literal

import json
import shutil
import threading
import time
from datetime import UTC, datetime

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Engine, create_engine, delete, select, update
from sqlalchemy.orm import Session

import numpy as np

from autoedit.auth import (
    LoginRateLimiter,
    create_session_token,
    hash_password,
    parse_session_token,
    verify_password,
)
from autoedit.ai.speaker_confirmation import ArtifactValidationError, artifact_version, load_artifact, snippets, validate_confirmation_payload
from autoedit.ai.activity_from_turns import activity_from_turns
from autoedit.activity import compute_activity_timeline
from autoedit.audio import SyncQualityError, compute_sync_offsets, extract_channel, extract_guide_track
from autoedit.conciseness import grade_conciseness
from autoedit.config import Settings
from autoedit.cdl_validator import frame_boundary_ms, ms_to_frames as cdl_ms_to_frames, validate_cdl
from autoedit.cut_engine import DEFAULT_CUT_PARAMS, _with_shot_reason, generate_cdl
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import (
    angles,
    audio_channels,
    cuts,
    jobs,
    notes,
    projects,
    speaker_confirmations,
    speaking_intervals,
    topics,
    topic_spans,
    transcript_segments,
    users,
)
from autoedit.intervals import compute_speaking_intervals
from autoedit.level_normalization import compute_level_normalization as build_level_normalization
from autoedit.level_normalization import gain_for_channel
from autoedit.loudness import compute_loudness_envelope
from autoedit.noise_floor import compute_noise_floor
from autoedit.diarize import mock_diarize
from autoedit.probe import probe_source_file
from autoedit.program_audio import generate_program_audio
from autoedit.project_paths import is_ulid, project_root
from autoedit.transcribe import mock_transcribe, transcribe_with_backend
from autoedit.projects import create_project as create_project_record
from autoedit.projects import get_project as get_project_record
from autoedit.projects import new_ulid
from autoedit.progress import compute_progress, set_project_status
from autoedit.proxy import generate_proxy
from autoedit.plog import PipelineLogger
from autoedit.report import build_summary
from autoedit.sub_edit import generate_sub_edit
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
    display_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    ] = "Operator"
    username: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    ] = None


class UserCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)]
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    role: Literal["admin", "reviewer"] = "reviewer"


class UploadCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    filename: str
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    role: Literal["cam_left", "cam_right", "wide", "other"]
    total_bytes: int = Field(gt=0, strict=True)
    total_chunks: int = Field(gt=0, strict=True)
    chunk_bytes: int | None = Field(default=None, gt=0, strict=True)


class UploadComplete(BaseModel):
    model_config = ConfigDict(strict=True)

    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")] | None = None
    total_bytes: int = Field(gt=0, strict=True)


class ChannelMappingEntry(BaseModel):
    model_config = ConfigDict(strict=True)

    source_angle_id: Annotated[str, StringConstraints(min_length=26, max_length=26)]
    channel_index: int = Field(ge=0, strict=True)
    speaker_label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class SyncNudge(BaseModel):
    model_config = ConfigDict(strict=True)

    source_angle_id: Annotated[str, StringConstraints(min_length=26, max_length=26)]
    offset_ms: int = Field(strict=True)


class ChannelMappingRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    mappings: list[ChannelMappingEntry] = Field(min_length=2)
    sync_nudges: list[SyncNudge] = []


class CutRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = "Rough cut"
    params: dict | None = None


class TimeRange(BaseModel):
    model_config = ConfigDict(strict=True)

    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(gt=0, strict=True)


class SubEditRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str = "Sub-edit"
    kind: Literal["themed", "manual"] = "themed"
    mode: Literal["by_topics", "minus_topics", "custom_ranges"] = "by_topics"
    topic_labels: list[str] | None = None
    exclude_labels: list[str] | None = None
    ranges: list[TimeRange] | None = None
    target_duration_secs: int | None = None
    params: dict | None = None


class NoteCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    t_ms: int = Field(ge=0)
    body: str = Field(min_length=1, max_length=10000)
    kind: Literal["note", "cut_suggestion"] = "note"


class SpeakerConfirmationRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    diarizer_speaker_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    speaker_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    camera_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=26, max_length=26)]
    source_run_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    source_artifact_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    evidence_turn_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = Field(min_length=2)
    expected_version: int | None = Field(default=None, ge=1, strict=True)


def _public_origin(public_domain: str | None) -> str | None:
    if not public_domain:
        return None
    domain = public_domain.strip().rstrip("/")
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"


def _origin_set(public_domain: str | None, allowed_origins: str = "") -> set[str]:
    origins = set()
    public_origin = _public_origin(public_domain)
    if public_origin:
        origins.add(public_origin)
    for raw in allowed_origins.split(","):
        origin = raw.strip().rstrip("/")
        if origin:
            origins.add(origin)
    return origins


def _is_public_path(path: str) -> bool:
    return (
        path == "/health"
        or path == "/auth/login"
        or path == "/login"
        or path.startswith("/.well-known/acme-challenge/")
        or path.startswith("/web/")
    )


def create_app(
    *,
    engine: Engine | None = None,
    data_root: str | Path | None = None,
    auth_enabled: bool | None = None,
    operator_password: str | None = None,
    operator_username: str | None = None,
    operator_display_name: str | None = None,
    session_secret: str | None = None,
    public_domain: str | None = None,
    allowed_origins: str | None = None,
    login_max_failures: int | None = None,
    login_lockout_seconds: int | None = None,
    session_cookie_name: str | None = None,
    session_cookie_secure: bool | None = None,
    upload_max_chunk_bytes: int | None = None,
    whisper_backend: str | None = None,
    sync_fn: object | None = None,
) -> FastAPI:
    settings = Settings()
    app_engine = engine or create_engine(settings.sqlalchemy_url)
    app_data_root = Path(data_root) if data_root is not None else settings.data_root

    app_auth_enabled = settings.auth_enabled if auth_enabled is None else auth_enabled
    app_operator_password = operator_password if operator_password is not None else settings.operator_password
    app_operator_username = operator_username or settings.operator_username
    app_operator_display_name = operator_display_name or settings.operator_display_name
    app_session_secret = session_secret if session_secret is not None else settings.session_secret
    app_public_domain = public_domain if public_domain is not None else settings.public_domain
    app_allowed_origins = allowed_origins if allowed_origins is not None else settings.allowed_origins
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
    allowed_origins = _origin_set(app_public_domain, app_allowed_origins)
    login_limiter = LoginRateLimiter(
        max_failures=app_login_max_failures,
        lockout_seconds=app_login_lockout_seconds,
    )
    app_proxy_encoder = settings.proxy_encoder
    app_proxy_gop = settings.proxy_gop
    app_proxy_height = settings.proxy_height
    app_proxy_crf = settings.proxy_crf
    app_proxy_low_height = settings.proxy_low_height
    app_proxy_low_crf = settings.proxy_low_crf
    app_upload_max_chunk_bytes = (
        upload_max_chunk_bytes
        if upload_max_chunk_bytes is not None
        else settings.upload_max_chunk_bytes
    )
    app_whisper_backend = whisper_backend or settings.whisper_backend
    app_whisper_backend = app_whisper_backend.strip().lower()
    if (
        whisper_backend is not None
        and app_whisper_backend not in {"mock", "whisperx"}
    ):
        raise ValueError(
            f"unsupported WHISPER_BACKEND {app_whisper_backend!r}; expected mock or whisperx"
        )
    app_ai_settings = settings.model_copy(
        update={"whisper_backend": app_whisper_backend}
    )
    transcription_locks: dict[str, threading.Lock] = {}
    transcription_locks_guard = threading.Lock()

    def _transcription_lock(project_id: str) -> threading.Lock:
        with transcription_locks_guard:
            return transcription_locks.setdefault(project_id, threading.Lock())

    def _proxy_filename(angle_id: str) -> str:
        return f"{angle_id}.proxy.mp4"

    def _channel_wav_filename(channel_id: str) -> str:
        return f"ch_{channel_id}.wav"

    def _probe_metadata_path(project_id: str, angle_id: str) -> Path:
        return project_root(app_data_root, project_id) / "metadata" / "probes" / f"{angle_id}.json"

    def _load_probe_metadata(project_id: str) -> dict[str, dict]:
        probe_dir = project_root(app_data_root, project_id) / "metadata" / "probes"
        if not probe_dir.is_dir():
            return {}
        result: dict[str, dict] = {}
        for path in probe_dir.glob("*.json"):
            angle_id = path.stem
            if not is_ulid(angle_id):
                continue
            try:
                result[angle_id] = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
        return result

    def _norm_label(value: str | None) -> str:
        return "".join(ch for ch in (value or "").lower() if ch.isalnum())

    def _audio_timeline_base_angle_id(channel_rows: list) -> str | None:
        """Choose the source angle whose channel WAV timeline drives activity/program audio."""
        counts: dict[str, int] = {}
        for ch in channel_rows:
            counts[ch.source_angle_id] = counts.get(ch.source_angle_id, 0) + 1
        if not counts:
            return None
        # Most mapped channels wins; ties preserve first channel-row order.
        first_seen = {ch.source_angle_id: idx for idx, ch in enumerate(channel_rows)}
        return max(counts, key=lambda aid: (counts[aid], -first_seen.get(aid, 0)))

    def _rebased_sync_offsets(angle_rows: list, base_angle_id: str | None) -> dict[str, int]:
        """Convert stored sync offsets into the activity/audio timeline basis.

        AutoEdit stores sync offsets in the source-time adjustment convention:
        a positive stored offset means source time is ahead of the reference
        timeline. If the activity/program timeline is based on another angle,
        subtract each angle from that base so generate_cdl's
        source_ms = timeline_ms - rebased_offset mapping produces the stored
        source-time adjustment.
        """
        raw_offsets = {a.id: int(a.sync_offset_ms or 0) for a in angle_rows}
        if base_angle_id is None or base_angle_id not in raw_offsets:
            return raw_offsets
        base_offset = raw_offsets[base_angle_id]
        return {angle_id: base_offset - offset for angle_id, offset in raw_offsets.items()}

    def _speaker_camera_map(angle_rows: list, channel_rows: list) -> dict[str, str]:
        """Map speaker labels to visible camera angles, not necessarily audio-source angles."""
        by_role = {a.role: a.id for a in angle_rows}
        by_label = {_norm_label(a.label): a.id for a in angle_rows}
        mapping: dict[str, str] = {}
        for ch in channel_rows:
            speaker = ch.speaker_label
            key = _norm_label(speaker)
            if not speaker:
                continue
            if key in {"presenter", "host", "speaker0", "speakera", "left"} and "cam_left" in by_role:
                mapping[speaker] = by_role["cam_left"]
            elif key in {"interviewee", "guest", "speaker1", "speakerb", "right"} and "cam_right" in by_role:
                mapping[speaker] = by_role["cam_right"]
            elif key in by_label:
                mapping[speaker] = by_label[key]
            else:
                # Fallback for projects where the channel mapping really is the
                # speaker camera mapping.
                mapping[speaker] = ch.source_angle_id
        return mapping

    def _media_type_for(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".mp4":
            return "video/mp4"
        if suffix == ".m4a":
            return "audio/mp4"
        if suffix == ".wav":
            return "audio/wav"
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def _read_tail(path: Path, n: int) -> list[str]:
        """Return the last N lines of a file efficiently."""
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                buf = bytearray()
                chunk_size = 4096
                while len(buf) < size and buf.count(b"\n") < n:
                    read_size = min(chunk_size, size - len(buf))
                    f.seek(max(0, size - len(buf) - read_size))
                    buf = f.read(read_size) + buf
                lines = buf.decode(errors="replace").splitlines()
                return lines[-n:]
        except OSError:
            return []

    def _check_and_update_status(project_id: str) -> None:
        """Re-evaluate project readiness and flip status if all stages are done."""
        try:
            progress = compute_progress(app_engine, app_data_root, project_id)
            if progress["ready"] and progress["status"] != "ready":
                set_project_status(app_engine, project_id, "ready")
            elif not progress["ready"] and progress["status"] == "created":
                set_project_status(app_engine, project_id, "processing")
        except Exception:
            pass  # Don't let status updates break the main operation

    def _is_db_known_media(project_id: str, kind: str, filename: str) -> bool:
        media_path = f"{kind}/{filename}"
        with Session(app_engine) as session:
            if kind == "proxy":
                return session.execute(
                    select(angles.c.id).where(
                        angles.c.project_id == project_id,
                        angles.c.proxy_path == media_path,
                    )
                ).first() is not None
            if kind == "proxy_low":
                return session.execute(
                    select(angles.c.id).where(
                        angles.c.project_id == project_id,
                        angles.c.proxy_low_path == media_path,
                    )
                ).first() is not None
            if kind == "audio":
                if media_path == "audio/program.m4a":
                    return True
                return session.execute(
                    select(audio_channels.c.id).where(
                        audio_channels.c.project_id == project_id,
                        audio_channels.c.wav_path == media_path,
                    )
                ).first() is not None
            if kind == "lut":
                # LUT files are validated on upload; allow any .cube in the luts/ dir
                return filename.endswith(".cube") and "/" not in filename and "\\" not in filename
            if kind == "edit":
                # Only the app-generated export deliverables are downloadable.
                # These are the URLs the /export endpoint hands back to the UI.
                return filename in ("export.fcpxml", "export.edl")
        return False

    def _upsert_operator_user() -> None:
        """Keep the configured operator account available in the users table."""
        if not app_operator_password or not app_operator_username:
            return
        password_hash = hash_password(app_operator_password)
        with Session(app_engine) as session:
            existing = session.execute(
                select(users).where(users.c.username == app_operator_username)
            ).first()
            if existing is None:
                session.execute(
                    users.insert().values(
                        id=new_ulid(),
                        username=app_operator_username,
                        pw_hash=password_hash,
                        display_name=app_operator_display_name,
                        role="admin",
                    )
                )
            else:
                session.execute(
                    users.update()
                    .where(users.c.username == app_operator_username)
                    .values(
                        pw_hash=password_hash,
                        display_name=app_operator_display_name,
                        role="admin",
                    )
                )
            session.commit()

    def _recover_orphaned_pipelines() -> None:
        """Mark projects stuck in 'processing' as 'error' on startup.

        The pipeline runs in an in-process background thread, so it cannot
        survive an app restart (deploy, crash, host reboot). Any project
        still marked 'processing' at boot is orphaned: its thread is gone,
        the progress endpoint would report a stage as 'running' forever,
        and /process would refuse to restart it. Flip it to 'error' so the
        UI shows the Retry button and the pipeline can be restarted.
        """
        with Session(app_engine) as session:
            stuck = session.execute(
                select(projects.c.id).where(projects.c.status == "processing")
            ).fetchall()
            if stuck:
                session.execute(
                    update(projects)
                    .where(projects.c.status == "processing")
                    .values(status="error")
                )
                session.commit()
        for row in stuck:
            try:
                project_dir = project_root(app_data_root, row.id)
                plog = PipelineLogger(project_dir, row.id)
                plog.error(
                    "Pipeline interrupted by application restart; use Retry processing to restart it."
                )
            except Exception:
                pass  # Logging is best-effort; status recovery already happened.

    def _sweep_stale_uploads(max_age_hours: float = 48.0) -> None:
        """Delete abandoned chunked-upload temp dirs on startup.

        A resumable upload that is started but never completed (the client
        gave up after a failed chunk, or the browser was closed mid-upload)
        leaves its chunks under <project>/.uploads/<upload_id>/ forever.
        For multi-gigabyte multicam sources this silently consumes disk.
        Successful and integrity-failed uploads already clean themselves up;
        this catches only the truly orphaned ones, identified by an mtime
        older than max_age_hours so an in-progress upload is never touched.
        """
        root = Path(app_data_root)
        if not root.is_dir():
            return
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        try:
            upload_dirs = list(root.glob("*/.uploads/*"))
        except OSError:
            return
        for upload_dir in upload_dirs:
            if not upload_dir.is_dir():
                continue
            try:
                # metadata.json is rewritten on each chunk, so its mtime
                # tracks the last activity for this upload.
                meta = upload_dir / "metadata.json"
                ref = meta if meta.exists() else upload_dir
                if ref.stat().st_mtime >= cutoff:
                    continue
                shutil.rmtree(upload_dir, ignore_errors=True)
                removed += 1
            except OSError:
                continue
        if removed:
            logging.getLogger("autoedit").info(
                "Startup: removed %d abandoned upload temp dir(s)", removed
            )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        run_migrations(app_engine)
        _upsert_operator_user()
        _recover_orphaned_pipelines()
        _sweep_stale_uploads()
        yield

    app = FastAPI(title="AUTOEDIT", version="0.1.0", lifespan=lifespan)
    web_dir = Path(__file__).with_name("web")
    app.mount("/web", StaticFiles(directory=web_dir), name="web")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    @app.middleware("http")
    async def security_gate(request: Request, call_next):
        origin = request.headers.get("Origin")
        if allowed_origins and origin and origin.rstrip("/") not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "origin not allowed"})

        if app_auth_enabled and not _is_public_path(request.url.path):
            token = request.cookies.get(app_session_cookie_name)
            session = None
            if token and app_session_secret:
                session = parse_session_token(token, secret=app_session_secret)
            if session is None:
                accept = request.headers.get("accept", "")
                if "text/html" in accept:
                    from starlette.responses import RedirectResponse
                    return RedirectResponse(f"/login?next={request.url.path}", status_code=302)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "authentication required"},
                )
            request.state.session = session

        return await call_next(request)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/login")
    def login_page():
        login_html = web_dir / "login.html"
        if login_html.is_file():
            return FileResponse(str(login_html), media_type="text/html")
        return HTMLResponse("<h1>Login page not found</h1>", status_code=404)

    @app.get("/")
    def app_home():
        return FileResponse(str(web_dir / "app.html"), media_type="text/html")

    @app.get("/ingest")
    def ingest_page():
        return FileResponse(str(web_dir / "app.html"), media_type="text/html")

    @app.get("/users/manage")
    def users_page():
        return FileResponse(str(web_dir / "app.html"), media_type="text/html")

    def _public_user(row) -> dict:
        return {
            "id": row.id,
            "username": row.username,
            "display_name": row.display_name,
            "role": row.role,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _require_admin(request: Request) -> None:
        # When auth is disabled there is no session gate; treat as operator/admin.
        if not app_auth_enabled:
            return
        session_data = getattr(request.state, "session", None) or {}
        # Fail closed: a session without an explicit admin role is not an admin.
        if session_data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="admin role required")

    def _login_client_key(request: Request) -> str:
        """Rate-limit key for the real client, not the reverse proxy.

        Behind Nginx Proxy Manager every request arrives from the proxy's IP,
        so keying on request.client.host would create one shared lockout
        bucket for the whole internet. NPM sets X-Forwarded-For; use the
        first (client) hop when present. Direct LAN requests have no XFF
        header and fall back to the socket peer address.
        """
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first_hop = forwarded.split(",")[0].strip()
            if first_hop:
                return first_hop
        return request.client.host if request.client else "unknown"

    @app.post("/auth/login", status_code=status.HTTP_204_NO_CONTENT)
    def login(payload: LoginRequest, request: Request) -> Response:
        client_key = _login_client_key(request)
        if not login_limiter.is_allowed(client_key):
            raise HTTPException(status_code=429, detail="too many failed login attempts")

        if not app_session_secret:
            raise HTTPException(status_code=503, detail="authentication is not configured")

        session_payload: dict | None = None
        if payload.username:
            with Session(app_engine) as session:
                user_row = session.execute(
                    select(users).where(users.c.username == payload.username)
                ).first()
            if user_row is not None:
                user = user_row._mapping
                if verify_password(payload.password, user["pw_hash"]):
                    session_payload = {
                        "display_name": user["display_name"],
                        "username": user["username"],
                        "role": user["role"],
                        "user_id": user["id"],
                    }

        if session_payload is None:
            requested_username = payload.username or ""
            if requested_username and requested_username != app_operator_username:
                login_limiter.record_failure(client_key)
                raise HTTPException(status_code=401, detail="invalid credentials")
            if not app_operator_password or not compare_digest(payload.password, app_operator_password):
                login_limiter.record_failure(client_key)
                raise HTTPException(status_code=401, detail="invalid credentials")
            if requested_username:
                _upsert_operator_user()
            session_payload = {
                "display_name": app_operator_display_name if requested_username else payload.display_name,
                "username": app_operator_username if requested_username else "operator",
                "role": "admin",
            }

        login_limiter.record_success(client_key)
        token = create_session_token(secret=app_session_secret, **session_payload)
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

    @app.get("/auth/session")
    def auth_session(request: Request) -> dict:
        session_data = request.state.session
        return {
            "display_name": session_data["display_name"],
            "username": session_data.get("username", "operator"),
            "role": session_data.get("role", "admin"),
        }

    @app.get("/users")
    def list_users(request: Request) -> dict:
        _require_admin(request)
        with Session(app_engine) as session:
            rows = session.execute(select(users).order_by(users.c.username)).all()
        return {"users": [_public_user(row) for row in rows]}

    @app.post("/users", status_code=status.HTTP_201_CREATED)
    def create_user(payload: UserCreate, request: Request) -> dict:
        _require_admin(request)
        user_id = new_ulid()
        try:
            password_hash = hash_password(payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with Session(app_engine) as session:
            existing = session.execute(
                select(users.c.id).where(users.c.username == payload.username)
            ).first()
            if existing is not None:
                raise HTTPException(status_code=400, detail="username already exists")
            session.execute(
                users.insert().values(
                    id=user_id,
                    username=payload.username,
                    pw_hash=password_hash,
                    display_name=payload.display_name,
                    role=payload.role,
                )
            )
            session.commit()
            row = session.execute(select(users).where(users.c.id == user_id)).one()
        return _public_user(row)

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

    @app.get("/projects")
    def list_projects() -> dict:
        with Session(app_engine) as session:
            rows = session.execute(
                select(projects).order_by(projects.c.created_at.desc(), projects.c.id.desc())
            ).all()
        return {"projects": [dict(row._mapping) for row in rows]}

    @app.get("/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return project

    @app.delete("/projects/{project_id}")
    def delete_project(project_id: str, request: Request, confirm: str = "") -> dict:
        """Delete a project and all its data.

        Admin-only: deletion permanently removes source media, proxies,
        transcripts, and exports, so reviewer accounts may not do it.
        Safety switch: requires ?confirm=DELETE to prevent accidents.
        Removes the project directory (all source files, proxies, audio,
        transcripts, exports) and all related DB rows.
        """
        _require_admin(request)
        if confirm != "DELETE":
            raise HTTPException(
                status_code=400,
                detail="add ?confirm=DELETE to permanently remove this project and all its data",
            )

        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)

        # Delete DB rows in order (children first to respect FKs)
        with Session(app_engine) as session:
            # Children of audio_channels (no direct project_id FK)
            session.execute(
                delete(speaking_intervals).where(
                    speaking_intervals.c.channel_id.in_(
                        select(audio_channels.c.id).where(
                            audio_channels.c.project_id == project_id
                        )
                    )
                )
            )
            session.execute(
                delete(transcript_segments).where(
                    transcript_segments.c.project_id == project_id
                )
            )

            # Children of topics
            session.execute(
                delete(topic_spans).where(topic_spans.c.project_id == project_id)
            )

            # Children of cuts
            session.execute(
                delete(notes).where(notes.c.project_id == project_id)
            )

            # Tables with direct project_id FK
            for table in [cuts, topics, audio_channels, angles, jobs]:
                session.execute(
                    delete(table).where(table.c.project_id == project_id)
                )

            # Finally, the project itself
            session.execute(
                delete(projects).where(projects.c.id == project_id)
            )
            session.commit()

        # Remove project directory from disk
        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

        return {"deleted": project_id, "name": project["name"]}

    @app.get("/projects/{project_id}/assets")
    def get_project_assets(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id).order_by(angles.c.label)
            ).all()
            channel_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
                .order_by(audio_channels.c.source_angle_id, audio_channels.c.channel_index)
            ).all()
        probe_metadata = _load_probe_metadata(project_id)
        angle_payload = []
        for row in angle_rows:
            item = dict(row._mapping)
            if item["id"] in probe_metadata:
                item["probe"] = probe_metadata[item["id"]]
            angle_payload.append(item)
        return {
            "project": project,
            "angles": angle_payload,
            "channels": [dict(row._mapping) for row in channel_rows],
            "probes": probe_metadata,
        }

    @app.get("/projects/{project_id}/progress")
    def get_project_progress(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        try:
            return compute_progress(app_engine, app_data_root, project_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/process")
    def start_pipeline(project_id: str) -> dict:
        """Start the full processing pipeline.

        Runs all pipeline stages sequentially and returns immediately.
        The client should poll GET /projects/{id}/progress for status.
        Each stage updates the project status; the progress endpoint
        shows which stages are done/in-progress/queued.
        """
        import threading

        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        # Check state. 'error' is allowed so the UI's "Retry processing"
        # button can restart a failed pipeline (previously it always 400'd).
        if project.get("status") not in ("created", "ingesting", "error"):
            raise HTTPException(
                status_code=400,
                detail=f"project status is '{project.get('status')}' — expected 'created', 'ingesting', or 'error'",
            )

        # Verify minimum requirements: channels mapped
        with Session(app_engine) as session:
            ch_count = session.execute(
                select(audio_channels.c.id).where(
                    audio_channels.c.project_id == project_id
                )
            ).fetchall()
            angle_count = session.execute(
                select(angles.c.id).where(
                    angles.c.project_id == project_id
                )
            ).fetchall()

        if len(ch_count) < 2:
            raise HTTPException(
                status_code=400,
                detail="at least two audio channels must be mapped before processing",
            )
        if len(angle_count) < 1:
            raise HTTPException(
                status_code=400,
                detail="at least one angle must be uploaded before processing",
            )

        set_project_status(app_engine, project_id, "processing")

        # Run stages sequentially in a background thread
        def _run_pipeline() -> None:
            project_dir = project_root(app_data_root, project_id)
            plog = PipelineLogger(project_dir, project_id)
            plog.info(f"Pipeline started for project {project_id[:8]}")
            try:
                # Stage order: sync → proxy → proxy-low → loudness → noise-floor
                #   → level-normalization → diarize → intervals → activity → program-audio
                #   → transcribe → segment-topics → conciseness → summary → cut

                with plog.stage("sync", "Audio sync & channel extraction"):
                    sync_project(project_id)

                with plog.stage("sync", "Main proxy generation"):
                    generate_all_proxies(project_id)

                with plog.stage("sync", "Low-bitrate proxy generation"):
                    generate_all_proxies_low(project_id)

                with plog.stage("loudness", "RMS energy envelope"):
                    compute_loudness(project_id)

                with plog.stage("noise_floor", "10th-percentile floor + 8dB margin"):
                    compute_noise_floors(project_id)

                with plog.stage("level_normalization", "Analysis level normalization"):
                    compute_level_normalization_stage(project_id)

                with plog.stage("diarize", "Speaker identification"):
                    diarize_speakers(project_id)

                with plog.stage("intervals", "VAD speaking intervals"):
                    compute_intervals(project_id)

                with plog.stage("activity", "Who-is-active timeline"):
                    compute_activity(project_id)

                with plog.stage("program_audio", "Stereo program mixdown"):
                    generate_audio_mixdown(project_id)

                with plog.stage("transcribe", "Per-speaker transcription"):
                    transcribe_audio(project_id)

                with plog.stage("segment_topics", "Topic segmentation"):
                    segment_topics(project_id)

                with plog.stage("conciseness", "Filler density & WPM grading"):
                    compute_conciseness(project_id)

                with plog.stage("summary", "Speaker time breakdown"):
                    build_project_summary(project_id)

                with plog.stage("cut", "Deterministic rough cut CDL"):
                    generate_cut(project_id)

                plog.info("Pipeline complete — all 13 stages passed")
            except Exception as exc:
                plog.error(f"Pipeline failed: {exc}")
                set_project_status(app_engine, project_id, "error")
                raise
            finally:
                _check_and_update_status(project_id)

        thread = threading.Thread(target=_run_pipeline, daemon=True)
        thread.start()

        return {
            "project_id": project_id,
            "status": "processing",
            "message": "Pipeline started. Poll /progress for status.",
        }

    @app.get("/projects/{project_id}/logs")
    def get_project_logs(project_id: str, lines: int = 100) -> dict:
        """Return the last N lines of the pipeline log."""
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        project_dir = project_root(app_data_root, project_id)
        log_path = project_dir / "pipeline.log"
        if not log_path.is_file():
            return {"project_id": project_id, "lines": [], "errors": {}}
        tail = _read_tail(log_path, max(1, min(lines, 500)))
        errors_path = project_dir / "pipeline.errors.json"
        errors = {}
        if errors_path.is_file():
            try:
                errors = json.loads(errors_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"project_id": project_id, "lines": tail, "errors": errors}

    def _strict_media_url(project_id: str, rel_path: str | None, kind: str) -> str | None:
        if not rel_path:
            return None
        prefix = f"{kind}/"
        if not rel_path.startswith(prefix):
            return None
        filename = rel_path.removeprefix(prefix)
        if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
            return None
        return f"/projects/{project_id}/media/{kind}/{filename}"

    @app.get("/projects/{project_id}/speaker-confirmations")
    def get_speaker_confirmations(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        artifact = load_artifact(project_root(app_data_root, project_id), strict=False)
        if artifact is None:
            raise HTTPException(status_code=400, detail="completed AI artifact not found")
        current_version = artifact_version(artifact)
        snippet_map = snippets(artifact)
        with Session(app_engine) as session:
            camera_rows = session.execute(select(angles).where(angles.c.project_id == project_id)).all()
            speaker_rows = session.execute(select(audio_channels.c.speaker_label).where(audio_channels.c.project_id == project_id)).all()
            rows = session.execute(select(speaker_confirmations).where(speaker_confirmations.c.project_id == project_id)).all()
        cameras = [{"id": row._mapping["id"], "label": row._mapping["label"], "role": row._mapping["role"]} for row in camera_rows]
        stable_speakers = sorted({str(row._mapping["speaker_label"]) for row in speaker_rows if row._mapping["speaker_label"]})
        confirmations = []
        for row in rows:
            item = dict(row._mapping)
            item["is_current"] = item["source_artifact_version"] == current_version
            if not item["is_current"]:
                item["status"] = "stale"
            item["confirmed_at"] = item["confirmed_at"].isoformat()
            confirmations.append(item)
        labels = []
        for label, turns in sorted(snippet_map.items()):
            current = next((item for item in confirmations if item["diarizer_speaker_id"] == label and item["is_current"]), None)
            historical = next((item for item in confirmations if item["diarizer_speaker_id"] == label), None)
            labels.append({"diarizer_speaker_id": label, "status": current["status"] if current else ("stale" if historical else "needs_confirmation"), "confirmation": current or historical, "snippets": [{**turn, "url": f"/projects/{project_id}/media/audio/program.m4a?start_ms={turn['start_ms']}&end_ms={turn['end_ms']}"} for turn in turns]})
        return {"artifact_version": current_version, "run_id": current_version, "speakers": stable_speakers, "cameras": cameras, "labels": labels}

    @app.put("/projects/{project_id}/speaker-confirmations")
    def save_speaker_confirmation(project_id: str, payload: SpeakerConfirmationRequest, request: Request) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        artifact = load_artifact(project_root(app_data_root, project_id), strict=False)
        if artifact is None:
            raise HTTPException(status_code=400, detail="completed AI artifact not found")
        current_version = artifact_version(artifact)
        if payload.source_run_id != current_version or payload.source_artifact_version != current_version:
            raise HTTPException(status_code=409, detail="stale AI artifact version; reload confirmation panel")
        try:
            validate_confirmation_payload(artifact=artifact, diarizer_speaker_id=payload.diarizer_speaker_id, speaker_id=payload.speaker_id, camera_id=payload.camera_id, evidence_turn_ids=payload.evidence_turn_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        operator = (getattr(request.state, "session", None) or {}).get("user_id") or (getattr(request.state, "session", None) or {}).get("username") or "operator"
        now = datetime.now(UTC).replace(tzinfo=None)
        with Session(app_engine) as session:
            camera = session.execute(select(angles.c.id).where(angles.c.id == payload.camera_id, angles.c.project_id == project_id)).scalar_one_or_none()
            if camera is None:
                raise HTTPException(status_code=400, detail="camera does not belong to project")
            existing = session.execute(select(speaker_confirmations).where(speaker_confirmations.c.project_id == project_id)).all()
            current = next((row._mapping for row in existing if row._mapping["diarizer_speaker_id"] == payload.diarizer_speaker_id), None)
            if payload.expected_version is not None and (current is None or current["version"] != payload.expected_version):
                raise HTTPException(status_code=409, detail="confirmation changed; reload before saving")
            for row in existing:
                item = row._mapping
                if item["diarizer_speaker_id"] != payload.diarizer_speaker_id and (item["speaker_id"] == payload.speaker_id or item["camera_id"] == payload.camera_id) and item["source_artifact_version"] == current_version:
                    raise HTTPException(status_code=409, detail="confirmation must be bijective; identity or camera is already used")
            values = {"project_id": project_id, "diarizer_speaker_id": payload.diarizer_speaker_id, "speaker_id": payload.speaker_id, "camera_id": payload.camera_id, "status": "confirmed", "operator_id": str(operator), "confirmed_at": now, "source_run_id": current_version, "source_artifact_version": current_version, "evidence_turn_ids": payload.evidence_turn_ids, "version": (current["version"] + 1 if current else 1)}
            if current:
                session.execute(speaker_confirmations.update().where(speaker_confirmations.c.id == current["id"]).values(**values))
                confirmation_id = current["id"]
            else:
                confirmation_id = new_ulid()
                session.execute(speaker_confirmations.insert().values(id=confirmation_id, **values))
            session.commit()
        return {"id": confirmation_id, **values, "confirmed_at": now.isoformat(), "artifact_version": current_version}

    @app.get("/projects/{project_id}/player-state")
    def get_player_state(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)
        if not (project_dir / "audio" / "program.m4a").is_file():
            raise HTTPException(
                status_code=400,
                detail="program audio not found — run /program-audio first",
            )

        with Session(app_engine) as session:
            latest_rough_cut_id = session.execute(
                select(cuts.c.id)
                .where(cuts.c.project_id == project_id, cuts.c.kind == "rough")
                .order_by(cuts.c.created_at.desc(), cuts.c.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            rough_cut = None
            if latest_rough_cut_id is not None:
                # MySQL can run out of sort memory when ORDER BY is applied to
                # rows that include large JSON columns (cdl_json). Sort only
                # narrow metadata first, then fetch the single selected cut.
                rough_cut = session.execute(
                    select(cuts).where(cuts.c.id == latest_rough_cut_id)
                ).first()
            angle_rows = session.execute(
                select(angles)
                .where(angles.c.project_id == project_id)
                .order_by(angles.c.id)
            ).all()
            channel_rows = session.execute(
                select(audio_channels)
                .where(audio_channels.c.project_id == project_id)
                .order_by(audio_channels.c.id)
            ).all()

        if rough_cut is None:
            raise HTTPException(
                status_code=400,
                detail="rough cut not found — run /cut first",
            )
        cut_row = rough_cut._mapping
        cdl = cut_row["cdl_json"] or {}

        player_angles = []
        raw_sync_offsets = {
            row._mapping["id"]: int(row._mapping["sync_offset_ms"] or 0)
            for row in angle_rows
        }
        base_angle_id = _audio_timeline_base_angle_id([row._mapping for row in channel_rows])
        base_sync_offset = raw_sync_offsets.get(base_angle_id, 0)
        for row in angle_rows:
            angle = row._mapping
            proxy_url = _strict_media_url(project_id, angle.get("proxy_path"), "proxy")
            if proxy_url is None:
                continue
            payload = {
                "id": angle["id"],
                "label": angle["label"],
                "role": angle["role"],
                "proxy_url": proxy_url,
                "sync_offset_ms": int(angle["sync_offset_ms"] or 0),
                # Convert the program-audio timeline to this angle's source time:
                # source_ms = timeline_ms + source_time_offset_ms.
                # This is for manual angle preview only; auto-cut clips already
                # carry synced src_in_ms in the CDL.
                "source_time_offset_ms": int(angle["sync_offset_ms"] or 0) - base_sync_offset,
            }
            proxy_low_url = _strict_media_url(project_id, angle.get("proxy_low_path"), "proxy_low")
            if proxy_low_url is not None:
                payload["proxy_low_url"] = proxy_low_url
            player_angles.append(payload)

        # Active LUT (default) + per-angle LUTs
        active_lut = None
        angle_luts: dict[str, dict] = {}
        lut_state_path = project_dir / "luts" / "state.json"
        if lut_state_path.is_file():
            lut_state = json.loads(lut_state_path.read_text())
            # Default
            active_fn = lut_state.get("default") or lut_state.get("active")
            if active_fn:
                lut_file = project_dir / "luts" / active_fn
                if lut_file.is_file():
                    try:
                        from autoedit.lut_io import parse_cube_header
                        header = parse_cube_header(lut_file.read_text())
                        active_lut = {
                            "filename": active_fn,
                            "title": header["title"],
                            "size": header["size"],
                            "url": f"/projects/{project_id}/media/lut/{active_fn}",
                        }
                    except (ValueError, UnicodeDecodeError):
                        pass
            # Per-angle assignments
            raw_angle_luts = lut_state.get("angle_luts", {})
            for aid, fn in raw_angle_luts.items():
                lut_file = project_dir / "luts" / fn
                if lut_file.is_file():
                    try:
                        from autoedit.lut_io import parse_cube_header
                        header = parse_cube_header(lut_file.read_text())
                        angle_luts[aid] = {
                            "filename": fn,
                            "title": header["title"],
                            "size": header["size"],
                            "url": f"/projects/{project_id}/media/lut/{fn}",
                        }
                    except (ValueError, UnicodeDecodeError):
                        pass

        try:
            ai_player_artifact = load_artifact(project_dir)
        except ArtifactValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        analysis_source = cdl.get("analysis_source", "vad")
        analysis_version = cdl.get("analysis_artifact_version")
        mapping_status = "baseline"
        if analysis_source == "whisperx" and ai_player_artifact is not None:
            mapping_status = "confirmed"
        elif ai_player_artifact is not None:
            mapping_status = "needs_confirmation"
        analysis_payload = {"source": analysis_source, "mapping_status": mapping_status}
        if analysis_version:
            analysis_payload["artifact_version"] = analysis_version
        return {
            "analysis": analysis_payload,
            "project": {
                "id": project["id"],
                "name": project["name"],
                "fps_num": project["fps_num"],
                "fps_den": project["fps_den"],
            },
            "audio": {
                "program_url": f"/projects/{project_id}/media/audio/program.m4a",
            },
            "angles": player_angles,
            "cut": {
                "id": cut_row["id"],
                "name": cut_row["name"],
                "params": cut_row["params_json"] or DEFAULT_CUT_PARAMS,
                "clips": cdl.get("clips", []),
            },
            "quality_default": "proxy",
            "active_lut": active_lut,
            "angle_luts": angle_luts,
        }

    @app.get("/projects/{project_id}/timeline-state")
    def get_timeline_state(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)

        # Load summary.json
        summary_path = project_dir / "transcript" / "summary.json"
        if not summary_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="summary.json not found — run /summary first",
            )
        summary = json.loads(summary_path.read_text())

        # Load rough cut CDL
        with Session(app_engine) as session:
            rough_cut = session.execute(
                select(cuts)
                .where(cuts.c.project_id == project_id, cuts.c.kind == "rough")
                .order_by(cuts.c.created_at.desc(), cuts.c.id.desc())
            ).first()

        if rough_cut is None:
            raise HTTPException(
                status_code=400,
                detail="rough cut not found — run /cut first",
            )
        cut_row = rough_cut._mapping
        cdl = cut_row["cdl_json"] or {}
        cdl_clips = cdl.get("clips", [])

        total_duration_ms = 0
        if cdl_clips:
            last = cdl_clips[-1]
            total_duration_ms = last["timeline_in_ms"] + last["dur_ms"]

        # Load angle info for colour mapping
        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()

        ANGLE_COLOURS = {
            "cam_left": "#4363d8",
            "cam_right": "#f58231",
            "wide": "#469990",
        }
        angle_map = {}
        for i, row in enumerate(angle_rows):
            angle = row._mapping
            role = (angle.get("role") or "").lower()
            colour = ANGLE_COLOURS.get(role, "#808080")
            angle_map[angle["id"]] = {
                "label": angle["label"],
                "role": angle.get("role"),
                "colour": colour,
            }

        result: dict = {
            "total_duration_ms": total_duration_ms,
            "summary": summary,
            "cdl_clips": cdl_clips,
            "angles": angle_map,
        }

        # Optionally include loudness
        loudness_path = project_dir / "audio" / "loudness.json"
        if loudness_path.is_file():
            result["loudness"] = json.loads(loudness_path.read_text())

        # Include notes
        with Session(app_engine) as session:
            note_rows = session.execute(
                select(notes)
                .where(notes.c.project_id == project_id)
                .order_by(notes.c.t_ms)
            ).fetchall()
        result["notes"] = [
            {
                "id": n.id,
                "t_ms": n.t_ms,
                "author": n.author,
                "body": n.body,
                "kind": n.kind,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in note_rows
        ]

        return result

    # ── LUT endpoints ──────────────────────────────────────────

    @app.post("/projects/{project_id}/luts", status_code=201)
    def upload_lut(project_id: str, file: UploadFile = File(...)) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        from autoedit.lut_io import safe_lut_filename, validate_cube

        try:
            filename = safe_lut_filename(file.filename or "upload.cube")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        content_bytes = file.file.read()
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="LUT file must be valid UTF-8")

        try:
            header = validate_cube(content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        project_dir = project_root(app_data_root, project_id)
        lut_dir = project_dir / "luts"
        lut_dir.mkdir(parents=True, exist_ok=True)
        (lut_dir / filename).write_bytes(content_bytes)

        return {
            "filename": filename,
            "title": header["title"],
            "size": header["size"],
        }

    @app.get("/projects/{project_id}/luts")
    def list_luts(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        from autoedit.lut_io import read_lut_state, parse_cube_header

        project_dir = project_root(app_data_root, project_id)
        lut_dir = project_dir / "luts"
        state = read_lut_state(project_dir)

        luts = []
        if lut_dir.is_dir():
            for f in sorted(lut_dir.glob("*.cube")):
                try:
                    content = f.read_text()
                    header = parse_cube_header(content)
                    luts.append({
                        "filename": f.name,
                        "title": header["title"],
                        "size": header["size"],
                    })
                except (ValueError, UnicodeDecodeError):
                    luts.append({
                        "filename": f.name,
                        "title": "",
                        "size": 0,
                    })

        return {
            "luts": luts,
            "active": state.get("default"),       # legacy compat
            "default": state.get("default"),
            "angle_luts": state.get("angle_luts", {}),
        }

    @app.post("/projects/{project_id}/luts/activate")
    def activate_lut(project_id: str, payload: dict) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        from autoedit.lut_io import set_default_lut

        filename = payload.get("filename", "")
        project_dir = project_root(app_data_root, project_id)
        lut_path = project_dir / "luts" / filename

        if not filename or not lut_path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"LUT file {filename} not found in project luts",
            )

        return set_default_lut(project_dir, filename)

    @app.post("/projects/{project_id}/luts/deactivate")
    def deactivate_lut(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        from autoedit.lut_io import set_default_lut

        project_dir = project_root(app_data_root, project_id)
        return set_default_lut(project_dir, None)

    @app.post("/projects/{project_id}/luts/assign")
    def assign_angle_lut_endpoint(project_id: str, payload: dict) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        from autoedit.lut_io import assign_angle_lut

        angle_id = payload.get("angle_id", "")
        filename = payload.get("filename", "")
        project_dir = project_root(app_data_root, project_id)
        lut_path = project_dir / "luts" / filename

        if not filename or not lut_path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"LUT file {filename} not found in project luts",
            )
        if not angle_id:
            raise HTTPException(status_code=400, detail="angle_id is required")

        return assign_angle_lut(project_dir, angle_id, filename)

    @app.post("/projects/{project_id}/luts/unassign")
    def unassign_angle_lut_endpoint(project_id: str, payload: dict) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        from autoedit.lut_io import unassign_angle_lut

        angle_id = payload.get("angle_id", "")
        if not angle_id:
            raise HTTPException(status_code=400, detail="angle_id is required")

        project_dir = project_root(app_data_root, project_id)
        return unassign_angle_lut(project_dir, angle_id)

    # ── Notes endpoints ───────────────────────────────────────

    @app.post("/projects/{project_id}/notes", status_code=201)
    def create_note(project_id: str, payload: NoteCreate, request: Request) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        author = "operator"
        if app_auth_enabled:
            session_data = getattr(request.state, "session", None)
            if session_data:
                author = session_data.get("display_name", author)

        with Session(app_engine) as session:
            result = session.execute(
                notes.insert().values(
                    project_id=project_id,
                    t_ms=payload.t_ms,
                    author=author,
                    body=payload.body,
                    kind=payload.kind,
                )
            )
            session.commit()
            note_id = result.lastrowid

            row = session.execute(
                select(notes).where(notes.c.id == note_id)
            ).first()

        return {
            "id": row.id,
            "project_id": row.project_id,
            "t_ms": row.t_ms,
            "author": row.author,
            "body": row.body,
            "kind": row.kind,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @app.get("/projects/{project_id}/notes")
    def list_notes(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            rows = session.execute(
                select(notes)
                .where(notes.c.project_id == project_id)
                .order_by(notes.c.t_ms)
            ).fetchall()

        return {
            "notes": [
                {
                    "id": r.id,
                    "project_id": r.project_id,
                    "t_ms": r.t_ms,
                    "author": r.author,
                    "body": r.body,
                    "kind": r.kind,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }

    @app.delete("/projects/{project_id}/notes/{note_id}")
    def delete_note(project_id: str, note_id: int) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            existing = session.execute(
                select(notes).where(notes.c.id == note_id, notes.c.project_id == project_id)
            ).first()
            if existing is None:
                raise HTTPException(status_code=404, detail="note not found")
            session.execute(delete(notes).where(notes.c.id == note_id))
            session.commit()

        return {"deleted": True}

    # ── Global LUT library ────────────────────────────────────

    @app.post("/luts", status_code=201)
    def upload_global_lut(file: UploadFile = File(...)) -> dict:
        from autoedit.lut_io import safe_lut_filename, validate_cube, global_lut_dir

        try:
            filename = safe_lut_filename(file.filename or "upload.cube")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        content_bytes = file.file.read()
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="LUT file must be valid UTF-8")

        try:
            header = validate_cube(content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        gld = global_lut_dir(app_data_root)
        gld.mkdir(parents=True, exist_ok=True)
        (gld / filename).write_bytes(content_bytes)

        return {
            "filename": filename,
            "title": header["title"],
            "size": header["size"],
        }

    @app.get("/luts")
    def list_global_luts_endpoint() -> dict:
        from autoedit.lut_io import list_global_luts
        return {"luts": list_global_luts(app_data_root)}

    # ── Export endpoint ──────────────────────────────────────

    @app.post("/projects/{project_id}/export")
    def export_project(project_id: str, payload: dict | None = None, export_format: str = "fcpxml") -> dict:
        """Export project to FCPXML (default) or EDL (with LOC markers for Resolve).

        Query: ?export_format=edl  or  Body: {"export_format": "edl"}
        Resolve limitation: FCPXML markers are ignored. Use edl for markers.
        """
        # Accept format from body or query param
        if payload and payload.get("export_format"):
            export_format = payload["export_format"]
        elif payload and payload.get("format"):
            export_format = payload["format"]  # legacy compat

        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        if export_format not in ("fcpxml", "edl"):
            raise HTTPException(status_code=400, detail="export_format must be 'fcpxml' or 'edl'")

        from autoedit.fcpxml_writer import write_fcpxml
        from autoedit.edl_writer import write_edl

        project_dir = project_root(app_data_root, project_id)

        # Load rough cut
        with Session(app_engine) as session:
            rough_cut = session.execute(
                select(cuts)
                .where(cuts.c.project_id == project_id, cuts.c.kind == "rough")
                .order_by(cuts.c.created_at.desc(), cuts.c.id.desc())
            ).first()

        if rough_cut is None:
            raise HTTPException(status_code=400, detail="rough cut not found — run /cut first")

        cut_row = rough_cut._mapping
        cdl = cut_row["cdl_json"] or {}

        # Load angles
        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()

        angle_list = [
            {
                "id": a.id,
                "label": a.label,
                "source_path": str(project_dir / (a.source_path or f"source/{a.id}.mp4")),
            }
            for a in angle_rows
        ]

        # Validate
        source_files = {}
        for a in angle_list:
            sp = Path(a["source_path"]) if a["source_path"] else None
            if sp and sp.is_file():
                source_files[a["id"]] = sp

        validation = validate_cdl(
            cdl,
            project["fps_num"],
            project["fps_den"],
            source_files=source_files,
        )

        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail=f"CDL validation failed: {validation['error']}",
            )

        # Write FCPXML
        # Load notes
        with Session(app_engine) as session:
            note_rows = session.execute(
                select(notes)
                .where(notes.c.project_id == project_id)
                .order_by(notes.c.t_ms)
            ).fetchall()
        notes_list = [
            {"t_ms": n.t_ms, "author": n.author, "body": n.body, "kind": n.kind}
            for n in note_rows
        ]

        # Write
        if export_format == "edl":
            output = project_dir / "edit" / "export.edl"
            output.parent.mkdir(parents=True, exist_ok=True)
            write_edl(
                cdl, project["fps_num"], project["fps_den"],
                angle_list, output, notes=notes_list,
            )
            url = f"/projects/{project_id}/media/edit/export.edl"
        else:
            output = project_dir / "edit" / "export.fcpxml"
            output.parent.mkdir(parents=True, exist_ok=True)
            write_fcpxml(
                cdl, project["fps_num"], project["fps_den"],
                angle_list, output, notes=notes_list,
            )
            url = f"/projects/{project_id}/media/edit/export.fcpxml"

        return {
            "status": "ok",
            "path": str(output),
            "url": url,
            "format": export_format,
        }

    @app.get("/player/{project_id}")
    def player_shell(project_id: str):
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        # Serve the player shell — player.js checks progress and shows
        # processing UI if the project isn't ready.
        return FileResponse(
            str(web_dir / "index.html"),
            media_type="text/html",
        )

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
                chunk_bytes=payload.chunk_bytes,
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
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > app_upload_max_chunk_bytes:
                    raise HTTPException(status_code=413, detail="upload chunk too large")
            except ValueError:
                raise HTTPException(status_code=400, detail="invalid content-length") from None

        body = await request.body()
        if len(body) > app_upload_max_chunk_bytes:
            raise HTTPException(status_code=413, detail="upload chunk too large")

        try:
            return write_upload_chunk(app_data_root, upload_id, index, body)
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
                expected_sha256=payload.sha256.lower() if payload.sha256 else None,
                expected_total_bytes=payload.total_bytes,
            )
        except UploadNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/angles/{angle_id}/probe")
    def probe_angle(project_id: str, angle_id: str) -> dict:
        if not is_ulid(angle_id):
            raise HTTPException(status_code=400, detail="invalid angle_id")
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            row = session.execute(
                select(angles).where(
                    angles.c.id == angle_id, angles.c.project_id == project_id
                )
            ).one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="angle not found")
            angle_row = row._mapping

            # Collect already-probed FPS values from other angles
            other_fps = session.execute(
                select(angles.c.src_fps_num, angles.c.src_fps_den).where(
                    angles.c.project_id == project_id,
                    angles.c.id != angle_id,
                    angles.c.src_fps_num.isnot(None),
                )
            ).all()

        # Confine source_path to the project directory
        source_path = project_root(app_data_root, project_id) / angle_row["source_path"]
        probe_data = probe_source_file(str(source_path))

        # ── Frame rate mismatch warnings ──────────────────────────
        src_num = probe_data["src_fps_num"]
        src_den = probe_data["src_fps_den"]
        proj_num = project["fps_num"]
        proj_den = project["fps_den"]

        if src_num * proj_den != proj_num * src_den:
            probe_data["warnings"].append(
                f"source frame rate {src_num}/{src_den} does not match "
                f"project frame rate {proj_num}/{proj_den}"
            )

        if other_fps:
            other_num, other_den = other_fps[0]
            if src_num * other_den != other_num * src_den:
                probe_data["warnings"].append(
                    f"source frame rate {src_num}/{src_den} differs from other "
                    f"angles ({other_num}/{other_den}) — all angles must share the "
                    f"same frame rate"
                )

        with Session(app_engine) as session:
            session.execute(
                angles.update().where(angles.c.id == angle_id).values(
                    width=probe_data["width"],
                    height=probe_data["height"],
                    vcodec=probe_data["vcodec"],
                    src_fps_num=src_num,
                    src_fps_den=src_den,
                    duration_ms=probe_data["duration_ms"],
                )
            )
            session.commit()

        probe_path = _probe_metadata_path(project_id, angle_id)
        probe_path.parent.mkdir(parents=True, exist_ok=True)
        probe_payload = {"angle_id": angle_id, **probe_data}
        tmp_path = probe_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(probe_payload, indent=2) + "\n")
        tmp_path.replace(probe_path)

        return probe_payload

    @app.post("/projects/{project_id}/channels", status_code=status.HTTP_201_CREATED)
    def set_channel_mapping(project_id: str, payload: ChannelMappingRequest) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        if len(payload.mappings) < 2:
            raise HTTPException(status_code=400, detail="at least two channel mappings required")

        # Validate unique (source_angle_id, channel_index) pairs
        seen = set()
        for entry in payload.mappings:
            key = (entry.source_angle_id, entry.channel_index)
            if key in seen:
                raise HTTPException(
                    status_code=400,
                    detail="duplicate channel_index for source_angle_id",
                )
            seen.add(key)

            # Verify angle exists and belongs to this project
            with Session(app_engine) as session:
                angle_row = session.execute(
                    select(angles).where(
                        angles.c.id == entry.source_angle_id,
                        angles.c.project_id == project_id,
                    )
                ).one_or_none()
            if angle_row is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"angle {entry.source_angle_id} not found in project",
                )

        with Session(app_engine) as session:
            old_channel_ids = [
                row.id
                for row in session.execute(
                    select(audio_channels.c.id).where(audio_channels.c.project_id == project_id)
                ).all()
            ]
            if old_channel_ids:
                session.execute(
                    delete(speaking_intervals).where(
                        speaking_intervals.c.channel_id.in_(old_channel_ids)
                    )
                )
                session.execute(
                    delete(transcript_segments).where(
                        transcript_segments.c.channel_id.in_(old_channel_ids)
                    )
                )

            # Replace existing audio_channels for this project
            session.execute(
                delete(audio_channels).where(audio_channels.c.project_id == project_id)
            )

            channels = []
            for entry in payload.mappings:
                channel_id = new_ulid()
                session.execute(
                    audio_channels.insert().values(
                        id=channel_id,
                        project_id=project_id,
                        speaker_label=entry.speaker_label,
                        source_angle_id=entry.source_angle_id,
                        channel_index=entry.channel_index,
                    )
                )
                channels.append({
                    "id": channel_id,
                    "project_id": project_id,
                    "speaker_label": entry.speaker_label,
                    "source_angle_id": entry.source_angle_id,
                    "channel_index": entry.channel_index,
                })

            # Apply sync nudges
            for nudge in payload.sync_nudges:
                session.execute(
                    angles.update()
                    .where(
                        angles.c.id == nudge.source_angle_id,
                        angles.c.project_id == project_id,
                    )
                    .values(sync_offset_ms=nudge.offset_ms)
                )

            session.commit()

        return {"channels": channels}

    @app.post("/projects/{project_id}/sync")
    def sync_project(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        if len(ch_rows) < 2:
            raise HTTPException(
                status_code=400,
                detail="at least two audio channels must be mapped before sync",
            )

        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()

        project_dir = project_root(app_data_root, project_id)
        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        # 1. Extract channel WAVs
        channels_result = []
        for ch in ch_rows:
            angle_row = next(
                (a for a in angle_rows if a.id == ch.source_angle_id), None
            )
            if angle_row is None:
                continue

            source_path = project_dir / angle_row.source_path
            wav_filename = _channel_wav_filename(ch.id)
            wav_path = audio_dir / wav_filename

            extract_channel(str(source_path), ch.channel_index, str(wav_path))

            wav_rel = f"audio/{wav_filename}"
            with Session(app_engine) as session:
                session.execute(
                    audio_channels.update()
                    .where(audio_channels.c.id == ch.id)
                    .values(wav_path=wav_rel)
                )
                session.commit()

            channels_result.append({
                "channel_id": ch.id,
                "speaker_label": ch.speaker_label,
                "wav_path": wav_rel,
            })

        # 2. Audio-based sync via energy-envelope cross-correlation
        angle_ids = sorted(a.id for a in angle_rows)
        if len(angle_ids) < 2:
            raise HTTPException(
                status_code=400,
                detail="at least two angles required for sync",
            )

        # Get operator nudge from existing angles (read before clearing)
        with Session(app_engine) as session:
            nudges = session.execute(
                select(angles.c.id, angles.c.sync_offset_ms).where(
                    angles.c.project_id == project_id
                )
            ).all()
        nudge_by_angle = {n.id: (n.sync_offset_ms or 0) for n in nudges}

        # Clear old offsets before computing new ones
        with Session(app_engine) as session:
            session.execute(
                angles.update().where(angles.c.project_id == project_id).values(sync_offset_ms=0)
            )
            session.commit()

        # Extract guide tracks and compute sync via energy-envelope correlation
        guide_tracks: dict[str, str] = {}
        for angle_row in angle_rows:
            source_path = project_dir / angle_row.source_path
            guide_filename = f"guide_{angle_row.id}.wav"
            guide_path = audio_dir / guide_filename
            extract_guide_track(str(source_path), str(guide_path))
            guide_tracks[angle_row.id] = str(guide_path)

        base_angle_id = _audio_timeline_base_angle_id(ch_rows)
        reference_id = base_angle_id if base_angle_id in guide_tracks else angle_ids[0]
        try:
            offsets = (sync_fn or compute_sync_offsets)(guide_tracks, reference_id)
        except SyncQualityError as exc:
            set_project_status(app_engine, project_id, "error")
            plog = PipelineLogger(project_dir, project_id)
            plog.error(str(exc))
            plog.record_error("sync", str(exc))
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "sync_quality_low",
                    "angle_id": exc.angle_id,
                    "quality": exc.quality,
                    "threshold": exc.threshold,
                    "message": str(exc),
                },
            ) from exc

        # Apply operator nudge additively without compounding previous auto-sync.
        offsets_result = []
        for angle_id in angle_ids:
            computed_offset = int(offsets.get(angle_id, 0))
            existing_offset = int(nudge_by_angle.get(angle_id, 0))
            if computed_offset == 0:
                # Reference angle: keep only small explicit manual nudges.
                # Large values are stale auto-sync from a previous reference
                # choice and must not be preserved as a nudge.
                nudge = existing_offset if abs(existing_offset) <= 2000 else 0
            elif existing_offset == 0:
                nudge = 0
            elif abs(existing_offset) <= 2000 and (
                abs(computed_offset) > 2000 or abs(existing_offset) < abs(computed_offset)
            ):
                # Small existing values that are smaller than the newly computed
                # offset are explicit manual nudges set before the first sync.
                nudge = existing_offset
            elif computed_offset != 0:
                if abs(existing_offset - computed_offset) <= 2000:
                    # Existing value is the previous auto-sync plus optional
                    # manual tweak; preserve only the residual tweak.
                    nudge = existing_offset - computed_offset
                elif abs(existing_offset - (2 * computed_offset)) <= 2000:
                    # Guard against older endpoint behaviour that compounded an
                    # auto-sync offset on rerun (old ~= computed + computed).
                    nudge = 0
                elif abs(existing_offset) <= 2000:
                    # Small existing values come from explicit manual nudges set
                    # before the first sync.
                    nudge = existing_offset
                else:
                    # Large unrelated values are almost certainly stale auto
                    # offsets from a previous algorithm. Do not add them again.
                    nudge = 0
            final_offset = computed_offset + nudge

            with Session(app_engine) as session:
                session.execute(
                    angles.update()
                    .where(angles.c.id == angle_id)
                    .values(sync_offset_ms=final_offset)
                )
                session.commit()

            offsets_result.append({
                "angle_id": angle_id,
                "offset_ms": final_offset,
            })

        _check_and_update_status(project_id)
        return {
            "channels": channels_result,
            "offsets": offsets_result,
        }

    @app.post("/projects/{project_id}/sync-nudge")
    def set_sync_nudge(project_id: str, payload: dict) -> dict:
        """Set manual sync nudges for angles from the player UI."""
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        nudges = payload.get("nudges", [])
        if not nudges:
            raise HTTPException(status_code=400, detail="nudges array required")
        with Session(app_engine) as session:
            for entry in nudges:
                aid = entry.get("source_angle_id")
                ms = int(entry.get("offset_ms", 0))
                if aid:
                    session.execute(
                        angles.update().where(
                            angles.c.id == aid, angles.c.project_id == project_id
                        ).values(sync_offset_ms=ms)
                    )
            session.commit()
        return {"status": "ok"}

    @app.post("/projects/{project_id}/proxy")
    def generate_all_proxies(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()

        project_dir = project_root(app_data_root, project_id)
        proxy_dir = project_dir / "proxy"
        proxy_dir.mkdir(parents=True, exist_ok=True)

        proxies = []
        for angle_row in angle_rows:
            source_path = project_dir / angle_row.source_path
            proxy_filename = _proxy_filename(angle_row.id)
            proxy_path = proxy_dir / proxy_filename

            generate_proxy(
                str(source_path), str(proxy_path),
                encoder=app_proxy_encoder,
                gop=app_proxy_gop,
                height=app_proxy_height,
                crf=app_proxy_crf,
            )

            proxy_rel = f"proxy/{proxy_filename}"
            with Session(app_engine) as session:
                session.execute(
                    angles.update()
                    .where(angles.c.id == angle_row.id)
                    .values(proxy_path=proxy_rel)
                )
                session.commit()

            proxies.append({
                "angle_id": angle_row.id,
                "proxy_path": proxy_rel,
            })

        _check_and_update_status(project_id)
        return {"proxies": proxies}

    @app.post("/projects/{project_id}/angles/{angle_id}/proxy")
    def generate_angle_proxy(project_id: str, angle_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            row = session.execute(
                select(angles).where(
                    angles.c.id == angle_id, angles.c.project_id == project_id
                )
            ).one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="angle not found")
            angle_row = row._mapping

        project_dir = project_root(app_data_root, project_id)
        proxy_dir = project_dir / "proxy"
        proxy_dir.mkdir(parents=True, exist_ok=True)

        source_path = project_dir / angle_row["source_path"]
        proxy_filename = _proxy_filename(angle_row["id"])
        proxy_path = proxy_dir / proxy_filename

        generate_proxy(
            str(source_path), str(proxy_path),
            encoder=app_proxy_encoder,
            gop=app_proxy_gop,
            height=app_proxy_height,
            crf=app_proxy_crf,
        )

        proxy_rel = f"proxy/{proxy_filename}"
        with Session(app_engine) as session:
            session.execute(
                angles.update()
                .where(angles.c.id == angle_id)
                .values(proxy_path=proxy_rel)
            )
            session.commit()

        _check_and_update_status(project_id)
        return {"angle_id": angle_id, "proxy_path": proxy_rel}

    @app.post("/projects/{project_id}/proxy-low")
    def generate_all_proxies_low(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()

        project_dir = project_root(app_data_root, project_id)
        proxy_dir = project_dir / "proxy_low"
        proxy_dir.mkdir(parents=True, exist_ok=True)

        proxies = []
        for angle_row in angle_rows:
            source_path = project_dir / angle_row.source_path
            proxy_filename = _proxy_filename(angle_row.id)
            proxy_path = proxy_dir / proxy_filename

            generate_proxy(
                str(source_path), str(proxy_path),
                encoder=app_proxy_encoder,
                gop=app_proxy_gop,
                height=app_proxy_low_height,
                crf=app_proxy_low_crf,
            )

            proxy_rel = f"proxy_low/{proxy_filename}"
            with Session(app_engine) as session:
                session.execute(
                    angles.update()
                    .where(angles.c.id == angle_row.id)
                    .values(proxy_low_path=proxy_rel)
                )
                session.commit()

            proxies.append({
                "angle_id": angle_row.id,
                "proxy_low_path": proxy_rel,
            })

        _check_and_update_status(project_id)
        return {"proxies": proxies}

    @app.post("/projects/{project_id}/angles/{angle_id}/proxy-low")
    def generate_angle_proxy_low(project_id: str, angle_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            row = session.execute(
                select(angles).where(
                    angles.c.id == angle_id, angles.c.project_id == project_id
                )
            ).one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="angle not found")
            angle_row = row._mapping

        project_dir = project_root(app_data_root, project_id)
        proxy_dir = project_dir / "proxy_low"
        proxy_dir.mkdir(parents=True, exist_ok=True)

        source_path = project_dir / angle_row["source_path"]
        proxy_filename = _proxy_filename(angle_row["id"])
        proxy_path = proxy_dir / proxy_filename

        generate_proxy(
            str(source_path), str(proxy_path),
            encoder=app_proxy_encoder,
            gop=app_proxy_gop,
            height=app_proxy_low_height,
            crf=app_proxy_low_crf,
        )

        proxy_rel = f"proxy_low/{proxy_filename}"
        with Session(app_engine) as session:
            session.execute(
                angles.update()
                .where(angles.c.id == angle_id)
                .values(proxy_low_path=proxy_rel)
            )
            session.commit()

        _check_and_update_status(project_id)
        return {"angle_id": angle_id, "proxy_low_path": proxy_rel}

    @app.get("/projects/{project_id}/media/{kind}/{filename:path}")
    def stream_media(project_id: str, kind: str, filename: str, request: Request):
        if kind not in ("proxy", "proxy_low", "audio", "lut", "edit"):
            raise HTTPException(status_code=400, detail="invalid media kind")

        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        # Confine to project directory
        project_dir = project_root(app_data_root, project_id)
        kind_dir = kind if kind != "lut" else "luts"
        resolved = (project_dir / kind_dir / filename).resolve()

        # Reject path traversal — must stay under project_dir/kind_dir/
        allowed_prefix = (project_dir / kind_dir).resolve()
        try:
            resolved.relative_to(allowed_prefix)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid path")

        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        if not _is_db_known_media(project_id, kind, filename):
            raise HTTPException(status_code=404, detail="file not found")

        return FileResponse(
            str(resolved),
            media_type=_media_type_for(resolved),
        )

    @app.post("/projects/{project_id}/loudness")
    def compute_loudness(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        if len(ch_rows) < 1:
            raise HTTPException(status_code=400, detail="no audio channels mapped")

        project_dir = project_root(app_data_root, project_id)
        audio_dir = project_dir / "audio"
        hop_ms = 20

        channels = {}
        for ch in ch_rows:
            if not ch.wav_path:
                continue
            wav_path = audio_dir / ch.wav_path.split("/")[-1]
            if not wav_path.is_file():
                continue

            import wave as _wave
            with _wave.open(str(wav_path), "rb") as wf:
                framerate = wf.getframerate()
                nframes = wf.getnframes()
                raw = wf.readframes(nframes)
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0

            rms_db = compute_loudness_envelope(samples, sample_rate=framerate, hop_ms=hop_ms)
            channels[ch.id] = {
                "rms_db": rms_db,
                "start_ms": 0,
            }

        result = {
            "hop_ms": hop_ms,
            "channels": channels,
        }

        loudness_path = audio_dir / "loudness.json"
        tmp_path = audio_dir / "loudness.json.tmp"
        tmp_path.write_text(json.dumps(result, indent=2) + "\n")
        tmp_path.replace(loudness_path)

        _check_and_update_status(project_id)
        return result

    @app.post("/projects/{project_id}/noise-floor")
    def compute_noise_floors(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)
        loudness_path = project_dir / "audio" / "loudness.json"
        if not loudness_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="loudness.json not found — run /loudness first",
            )

        loudness = json.loads(loudness_path.read_text())
        channels_data = loudness.get("channels", {})

        results = {}
        for ch_id, ch_data in channels_data.items():
            floor, threshold = compute_noise_floor(ch_data["rms_db"])
            with Session(app_engine) as session:
                session.execute(
                    audio_channels.update()
                    .where(audio_channels.c.id == ch_id)
                    .values(noise_floor_db=floor, vad_threshold_db=threshold)
                )
                session.commit()
            results[ch_id] = {
                "noise_floor_db": floor,
                "vad_threshold_db": threshold,
            }

        _check_and_update_status(project_id)
        return {"channels": results}

    @app.post("/projects/{project_id}/level-normalization")
    def compute_level_normalization_stage(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        if not ch_rows:
            raise HTTPException(
                status_code=400,
                detail="no audio channels found — map channels first",
            )
        if any(ch.vad_threshold_db is None for ch in ch_rows):
            raise HTTPException(
                status_code=400,
                detail="vad thresholds missing — run /noise-floor first",
            )

        result = build_level_normalization(ch_rows)
        project_dir = project_root(app_data_root, project_id)
        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = audio_dir / "level_normalization.json.tmp"
        tmp_path.write_text(json.dumps(result, indent=2) + "\n")
        tmp_path.replace(audio_dir / "level_normalization.json")

        _check_and_update_status(project_id)
        return result

    @app.post("/projects/{project_id}/intervals")
    def compute_intervals(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)
        loudness_path = project_dir / "audio" / "loudness.json"
        if not loudness_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="loudness.json not found — run /loudness first",
            )

        loudness = json.loads(loudness_path.read_text())
        hop_ms = loudness.get("hop_ms", 20)
        channels_data = loudness.get("channels", {})

        if not channels_data:
            raise HTTPException(
                status_code=400,
                detail="loudness.json has no channel data",
            )

        # Load threshold from DB
        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        threshold_by_channel = {}
        for ch in ch_rows:
            if ch.vad_threshold_db is not None:
                threshold_by_channel[ch.id] = ch.vad_threshold_db

        if not threshold_by_channel:
            raise HTTPException(
                status_code=400,
                detail="no vad_threshold_db found — run /noise-floor first",
            )

        # Delete old intervals for this project's channels
        with Session(app_engine) as session:
            ch_ids = [ch.id for ch in ch_rows]
            if ch_ids:
                session.execute(
                    speaking_intervals.delete().where(
                        speaking_intervals.c.channel_id.in_(ch_ids)
                    )
                )
                session.commit()

        all_intervals = []
        for ch_id, ch_data in channels_data.items():
            threshold = threshold_by_channel.get(ch_id)
            if threshold is None:
                continue

            intervals = compute_speaking_intervals(
                ch_data["rms_db"],
                hop_ms=hop_ms,
                threshold_db=threshold,
                start_ms=ch_data.get("start_ms", 0),
            )

            if intervals:
                with Session(app_engine) as session:
                    for ival in intervals:
                        session.execute(
                            speaking_intervals.insert().values(
                                channel_id=ch_id,
                                start_ms=ival["start_ms"],
                                end_ms=ival["end_ms"],
                                mean_db=ival["mean_db"],
                                peak_db=ival["peak_db"],
                            )
                        )
                    session.commit()

            all_intervals.append({
                "channel_id": ch_id,
                "intervals": intervals,
            })

        _check_and_update_status(project_id)
        return {
            "intervals": all_intervals,
            "channel_count": len(all_intervals),
        }

    @app.post("/projects/{project_id}/activity")
    def compute_activity(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)
        audio_dir = project_dir / "audio"
        normalization: dict = {}
        normalization_path = audio_dir / "level_normalization.json"
        if normalization_path.is_file():
            try:
                normalization = json.loads(normalization_path.read_text())
            except (json.JSONDecodeError, OSError):
                normalization = {}

        # Load speaking intervals from DB
        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        if not ch_rows:
            raise HTTPException(
                status_code=400,
                detail="no audio channels found — map channels first",
            )

        channel_intervals = []
        max_end = 0
        with Session(app_engine) as session:
            for ch in ch_rows:
                si_rows = session.execute(
                    select(speaking_intervals).where(
                        speaking_intervals.c.channel_id == ch.id
                    ).order_by(speaking_intervals.c.start_ms)
                ).all()

                if not si_rows:
                    continue

                level_gain_db = gain_for_channel(normalization, ch.id)
                intervals = [
                    {
                        "start_ms": int(si.start_ms),
                        "end_ms": int(si.end_ms),
                        "mean_db": float(si.mean_db) if si.mean_db is not None else None,
                        "level_gain_db": level_gain_db,
                    }
                    for si in si_rows
                ]
                channel_intervals.append({
                    "channel_id": ch.id,
                    "speaker_label": ch.speaker_label,
                    "intervals": intervals,
                })
                for si in si_rows:
                    if si.end_ms > max_end:
                        max_end = int(si.end_ms)

        if not channel_intervals:
            raise HTTPException(
                status_code=400,
                detail=(
                    "no speech was detected in any mapped audio channel. "
                    "Check that the correct channels are mapped and that the "
                    "recordings contain audible speech above the noise floor. "
                    "If processing was interrupted, retry it so the VAD "
                    "intervals stage runs again."
                ),
            )

        timeline = compute_activity_timeline(channel_intervals, total_duration_ms=max_end)

        # Write activity.json
        result = {
            "timeline": timeline,
            "total_duration_ms": max_end,
        }
        tmp_path = audio_dir / "activity.json.tmp"
        tmp_path.write_text(json.dumps(result, indent=2) + "\n")
        tmp_path.replace(audio_dir / "activity.json")

        _check_and_update_status(project_id)
        return result

    @app.post("/projects/{project_id}/program-audio")
    def generate_audio_mixdown(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        if len(ch_rows) < 1:
            raise HTTPException(
                status_code=400,
                detail="no audio channels found — map channels first",
            )

        # Load sync offsets per angle
        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()
        offset_by_angle = _rebased_sync_offsets(angle_rows, _audio_timeline_base_angle_id(ch_rows))

        project_dir = project_root(app_data_root, project_id)
        audio_dir = project_dir / "audio"

        channel_wavs = []
        for ch in ch_rows:
            if not ch.wav_path:
                continue
            wav_abs = audio_dir / ch.wav_path.split("/")[-1]
            if not wav_abs.is_file():
                continue
            offset = offset_by_angle.get(ch.source_angle_id, 0)
            channel_wavs.append((str(wav_abs), int(offset)))

        if not channel_wavs:
            raise HTTPException(
                status_code=400,
                detail="no WAV files found — run /sync first",
            )

        output_path = audio_dir / "program.m4a"
        generate_program_audio(channel_wavs, str(output_path))

        _check_and_update_status(project_id)
        return {
            "path": "audio/program.m4a",
            "channels": len(channel_wavs),
        }

    @app.post("/projects/{project_id}/cut")
    def generate_cut(project_id: str, payload: CutRequest | None = None) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)
        activity_path = project_dir / "audio" / "activity.json"
        if not activity_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="activity.json not found — run /activity first",
            )

        activity = json.loads(activity_path.read_text())
        timeline = activity.get("timeline", [])
        if not timeline:
            raise HTTPException(
                status_code=400,
                detail="activity timeline is empty",
            )

        # Load angle and channel data
        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        # Build speaker→visible-camera mapping. The audio channel source may be a
        # separate recorder/camera, so do not use it directly for speaker cuts.
        speaker_to_angle = _speaker_camera_map(angle_rows, ch_rows)

        # A completed WhisperX artifact becomes authoritative only after the
        # operator's current, bijective confirmations are present.  Never use
        # suggested artifact mappings or silently fall back to VAD in this path.
        try:
            ai_artifact = load_artifact(project_dir)
        except ArtifactValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if ai_artifact is not None:
            current_version = artifact_version(ai_artifact)
            with Session(app_engine) as session:
                confirmation_rows = session.execute(
                    select(speaker_confirmations).where(
                        speaker_confirmations.c.project_id == project_id,
                        speaker_confirmations.c.source_artifact_version == current_version,
                        speaker_confirmations.c.status == "confirmed",
                    )
                ).all()
            confirmations = {row._mapping["diarizer_speaker_id"]: row._mapping for row in confirmation_rows}
            observed = {str(turn["diarizer_speaker_id"]) for turn in ai_artifact.get("diarization_turns", [])}
            if observed != set(confirmations):
                raise HTTPException(
                    status_code=409,
                    detail="current speaker confirmations are required before generating the AI cut",
                )
            speaker_to_angle = {item["speaker_id"]: item["camera_id"] for item in confirmations.values()}
            resolved_ids = {str(turn["source_turn_id"]) for turn in ai_artifact.get("speaker_turns", [])
                            if turn.get("provenance") in {"confirmed_mapping", "prior_confirmed_mapping"}}
            turns = [
                {"start_ms": int(turn["start_ms"]), "end_ms": int(turn["end_ms"]),
                 "speaker_id": next((item["speaker_id"] for item in confirmations.values()
                                      if item["diarizer_speaker_id"] == turn["diarizer_speaker_id"]), None),
                 "confidence": turn.get("confidence")}
                for turn in ai_artifact.get("speaker_turns", [])
                if turn.get("provenance") in {"confirmed_mapping", "prior_confirmed_mapping"}
            ]
            turns.extend(
                {"start_ms": int(turn["start_ms"]), "end_ms": int(turn["end_ms"]),
                 "speaker_id": None, "confidence": turn.get("confidence")}
                for turn in ai_artifact.get("diarization_turns", [])
                if str(turn["turn_id"]) not in resolved_ids
            )
            try:
                timeline = activity_from_turns(turns, timeline_end_ms=int(ai_artifact["timeline_end_ms"]), confidence_threshold=0.5)
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"invalid AI activity artifact: {exc}") from exc
            activity = {"timeline": timeline, "total_duration_ms": int(ai_artifact["timeline_end_ms"]),
                        "source": "whisperx", "artifact_version": current_version}
            (project_dir / "audio" / "ai" / "v1").mkdir(parents=True, exist_ok=True)
            tmp_activity = project_dir / "audio" / "ai" / "v1" / "activity-whisperx.json.tmp"
            tmp_activity.write_text(json.dumps(activity, indent=2) + "\n")
            tmp_activity.replace(project_dir / "audio" / "ai" / "v1" / "activity-whisperx.json")

        # Build sync offsets in the same timeline basis as activity.json. The
        # activity timeline comes from extracted speaker channel WAVs, so its
        # zero is the primary audio-source angle, not necessarily the wide angle.
        base_angle_id = _audio_timeline_base_angle_id(ch_rows)
        sync_offsets = _rebased_sync_offsets(angle_rows, base_angle_id)

        # Find wide angle
        wide_angle_id = None
        for a in angle_rows:
            if a.role == "wide":
                wide_angle_id = a.id
                break

        # Generate CDL
        cut_params = payload.params if payload else None
        try:
            cdl = generate_cdl(
                timeline,
                speaker_to_angle,
                sync_offsets,
                wide_angle_id=wide_angle_id,
                fps_num=project["fps_num"],
                fps_den=project["fps_den"],
                params=cut_params,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"cut generation failed closed: {exc}") from exc
        cdl["project_id"] = project_id

        # ── Clamp trailing clips to available source media ────────────
        # The activity timeline extends to the end of the longest audio
        # channel, but a clip's assigned angle (often the wide) may have
        # stopped recording earlier, or a sync offset may shift its source
        # range past the end of the file. NLEs render such over-runs as
        # black gaps in the edit. Trim the timeline tail so the last clip
        # never references source media past its probed duration; only the
        # tail is touched, so clip contiguity is preserved.
        angle_duration_ms = {
            a.id: int(a.duration_ms) for a in angle_rows if a.duration_ms
        }
        fnum, fden = project["fps_num"], project["fps_den"]
        clips_list = cdl.get("clips", [])

        def _snap_ms(value: int) -> int:
            return frame_boundary_ms(cdl_ms_to_frames(value, fnum, fden), fnum, fden)

        def _floor_frame_ms(value: int) -> int:
            frame = (value * fnum) // (fden * 1000)
            ms = frame_boundary_ms(frame, fnum, fden)
            while ms > value and frame > 0:
                frame -= 1
                ms = frame_boundary_ms(frame, fnum, fden)
            return ms

        def _source_clip(angle_id: str, t_in: int, t_out: int, reason: str) -> dict | None:
            dur = t_out - t_in
            if dur <= 0:
                return None
            src_in = _snap_ms(t_in - int(sync_offsets.get(angle_id, 0)))
            return _with_shot_reason({
                "angle_id": angle_id,
                "src_in_ms": src_in,
                "timeline_in_ms": t_in,
                "dur_ms": dur,
            }, reason)

        def _clip_within_source(clip: dict) -> bool:
            src_in = int(clip["src_in_ms"])
            if src_in < 0:
                return False
            media_ms = angle_duration_ms.get(clip["angle_id"])
            if media_ms is not None and src_in + int(clip["dur_ms"]) > media_ms:
                return False
            return True

        def _fallback_clip(t_in: int, t_out: int, original: dict, previous_angle_id: str | None) -> dict | None:
            preferred = ([wide_angle_id] if ai_artifact is not None else [base_angle_id, previous_angle_id, *speaker_to_angle.values()])
            seen: set[str] = set()
            for angle_id in preferred:
                if not angle_id or angle_id in seen or angle_id == original["angle_id"]:
                    continue
                seen.add(angle_id)
                candidate = _source_clip(
                    angle_id,
                    t_in,
                    t_out,
                    f"source_unavailable:{original['angle_id']}:{original.get('reason', '')}",
                )
                if candidate is not None and _clip_within_source(candidate):
                    return candidate
            return None

        repaired_clips: list[dict] = []
        for clip in clips_list:
            t_in = int(clip["timeline_in_ms"])
            t_out = t_in + int(clip["dur_ms"])
            src_in = int(clip["src_in_ms"])
            if src_in < 0:
                # The requested camera has no source frame yet. Fill the
                # unavailable leading span with an already-available angle,
                # then resume the requested angle at source time zero if the
                # clip extends far enough. This prevents the browser/NLE from
                # clamping to frame 0 and repeating it.
                available_from = _snap_ms(t_in - src_in)
                split_at = min(max(available_from, t_in), t_out)
                fallback = _fallback_clip(
                    t_in,
                    split_at,
                    clip,
                    repaired_clips[-1]["angle_id"] if repaired_clips else None,
                )
                if fallback is not None:
                    repaired_clips.append(fallback)
                if split_at < t_out:
                    resumed = _source_clip(clip["angle_id"], split_at, t_out, clip.get("reason", ""))
                    if resumed is not None and _clip_within_source(resumed):
                        repaired_clips.append(resumed)
                continue
            media_ms = angle_duration_ms.get(clip["angle_id"])
            if media_ms is not None and src_in + int(clip["dur_ms"]) > media_ms:
                # The requested camera runs out before this timeline segment
                # ends. Keep the valid leading portion and fill the overrun
                # tail from another available angle instead of saving a clip
                # that exports as black or repeats/clamps at the end.
                valid_until = _floor_frame_ms(t_in + max(0, media_ms - src_in))
                split_at = min(max(valid_until, t_in), t_out)
                if split_at > t_in:
                    leading = dict(clip)
                    leading["dur_ms"] = split_at - t_in
                    if _clip_within_source(leading):
                        repaired_clips.append(leading)
                if split_at < t_out:
                    fallback = _fallback_clip(
                        split_at,
                        t_out,
                        clip,
                        repaired_clips[-1]["angle_id"] if repaired_clips else None,
                    )
                    if fallback is not None:
                        repaired_clips.append(fallback)
                continue
            repaired_clips.append(clip)
        clips_list[:] = repaired_clips

        # An AI-authoritative cut must cover the whole accepted master timeline.
        # A missing/exhausted wide source is a visible failure, never a partial
        # CDL or an arbitrary close-up fallback.
        if ai_artifact is not None:
            expected_end = int(ai_artifact["timeline_end_ms"])
            actual_end = (
                clips_list[-1]["timeline_in_ms"] + clips_list[-1]["dur_ms"]
                if clips_list else None
            )
            if not clips_list or clips_list[0]["timeline_in_ms"] != 0 or actual_end != expected_end:
                raise HTTPException(status_code=422, detail="AI cut generation failed closed: no complete source-bound CDL")

        while clips_list:
            last = clips_list[-1]
            media_ms = angle_duration_ms.get(last["angle_id"])
            if media_ms is None:
                break
            available = media_ms - last["src_in_ms"]
            if last["dur_ms"] <= available:
                break
            # Snap the clip END down onto the canonical frame grid (the same
            # grid the cut engine and validator use), keeping it within the
            # available media. Flooring the duration onto a raw frame grid
            # here would leave the end off-grid at NTSC rates and fail the
            # validator's boundary check at export time.
            max_end_ms = last["timeline_in_ms"] + available
            end_frame = (max_end_ms * fnum) // (fden * 1000)
            end_ms = frame_boundary_ms(end_frame, fnum, fden)
            while end_ms > max_end_ms and end_frame > 0:
                end_frame -= 1
                end_ms = frame_boundary_ms(end_frame, fnum, fden)
            clamped = end_ms - last["timeline_in_ms"]
            if clamped > 0:
                last["dur_ms"] = clamped
                break
            clips_list.pop()  # Entirely past media end; expose the previous clip.

        # Surface any remaining source-bounds problems (e.g. a mid-timeline
        # clip overrunning a short angle) as a warning the UI can show,
        # rather than leaving them to appear as black gaps in Resolve.
        cut_validation = validate_cdl(
            cdl,
            project["fps_num"],
            project["fps_den"],
            source_durations_ms=angle_duration_ms,
        )
        cdl["validation"] = cut_validation
        if not cut_validation.get("valid"):
            raise HTTPException(
                status_code=422,
                detail=f"cut generation failed closed: {cut_validation.get('error', 'invalid CDL')}",
            )
        cdl["analysis_source"] = "whisperx" if ai_artifact is not None else "vad"
        if ai_artifact is not None:
            cdl["analysis_artifact_version"] = artifact_version(ai_artifact)

        # Write edit/cdl.json
        edit_dir = project_dir / "edit"
        edit_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = edit_dir / "cdl.json.tmp"
        tmp_path.write_text(json.dumps(cdl, indent=2) + "\n")
        tmp_path.replace(edit_dir / "cdl.json")

        # Persist to cuts table
        effective_params = dict(DEFAULT_CUT_PARAMS)
        if cut_params:
            effective_params.update(cut_params)

        cut_name = payload.name if payload else "Rough cut"
        cut_id = new_ulid()
        with Session(app_engine) as session:
            session.execute(
                cuts.insert().values(
                    id=cut_id,
                    project_id=project_id,
                    name=cut_name,
                    kind="rough",
                    params_json=effective_params,
                    cdl_json=cdl,
                )
            )
            session.commit()

        _check_and_update_status(project_id)
        return cdl

    @app.post("/projects/{project_id}/cut/review")
    async def review_cut(project_id: str) -> dict:
        """Review the generated cut for quality issues using LLM."""
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)

        # Load CDL
        cdl_path = project_dir / "edit" / "cdl.json"
        if not cdl_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="cdl.json not found — run /cut first",
            )
        cdl = json.loads(cdl_path.read_text())

        # Load activity timeline
        activity_path = project_dir / "audio" / "activity.json"
        if not activity_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="activity.json not found — run /activity first",
            )
        activity = json.loads(activity_path.read_text())
        timeline = activity.get("timeline", [])

        # Load transcript
        transcript_path = project_dir / "transcript" / "transcript.json"
        transcript_segments = []
        if transcript_path.is_file():
            transcript = json.loads(transcript_path.read_text())
            transcript_segments = transcript.get("segments", [])

        # Load angle labels
        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()
        angle_labels = {a.id: a.label for a in angle_rows}

        # Run LLM review
        settings = Settings()
        if not settings.llm_model or not settings.ollama_base_url:
            return {
                "reviewed": False,
                "reason": "LLM not configured (set OLLAMA_BASE_URL and LLM_MODEL)",
            }

        from autoedit.cut_review import review_cut_quality, format_cut_review_for_ui
        review = await review_cut_quality(cdl, transcript_segments, timeline, angle_labels, settings)

        if review:
            ui_notes = format_cut_review_for_ui(review)
            # Optionally save review notes to project
            return {
                "reviewed": True,
                "overall_rating": review.get("overall_rating"),
                "summary": review.get("summary"),
                "issues": review.get("issues", []),
                "ui_notes": ui_notes,
            }
        else:
            return {
                "reviewed": False,
                "reason": "LLM review failed or unavailable",
            }

    def _transcribe_audio_locked(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()

        if len(ch_rows) < 1:
            raise HTTPException(
                status_code=400,
                detail="no audio channels found — map channels first",
            )

        offset_by_angle = {a.id: (a.sync_offset_ms or 0) for a in angle_rows}
        project_dir = project_root(app_data_root, project_id)
        audio_dir = project_dir / "audio"

        import wave as _wave

        prepared_channels = []
        for ch in ch_rows:
            channel_name = ch.speaker_label or ch.id
            if not ch.wav_path:
                raise HTTPException(
                    status_code=400,
                    detail=f"audio channel {channel_name!r} has no WAV path — run /sync first",
                )
            wav_abs = audio_dir / ch.wav_path.split("/")[-1]
            if not wav_abs.is_file():
                raise HTTPException(
                    status_code=400,
                    detail=f"WAV for audio channel {channel_name!r} is missing — run /sync first",
                )
            try:
                with _wave.open(str(wav_abs), "rb") as wf:
                    framerate = wf.getframerate()
                    nframes = wf.getnframes()
            except (_wave.Error, OSError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"WAV for audio channel {channel_name!r} is invalid: {exc}",
                ) from exc
            if framerate <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"WAV for audio channel {channel_name!r} has an invalid sample rate",
                )
            prepared_channels.append((ch, wav_abs, framerate, nframes))

        all_segments = []
        for ch, wav_abs, framerate, nframes in prepared_channels:
            # Stored convention: source_ms = master_ms + sync_offset_ms.
            # Transcription needs source -> master, so subtract exactly once.
            timeline_shift_ms = -int(offset_by_angle.get(ch.source_angle_id, 0))
            if app_whisper_backend.strip().lower() == "mock":
                # Keep this direct call as a stable test seam and as the explicit
                # development backend. Production backends must never silently
                # fall back to generated transcript text.
                result = mock_transcribe(
                    framerate,
                    duration_samples=nframes,
                    start_ms=timeline_shift_ms,
                    speaker_label=ch.speaker_label,
                )
            else:
                try:
                    result = transcribe_with_backend(
                        wav_abs,
                        settings=app_ai_settings,
                        start_ms=timeline_shift_ms,
                        speaker_label=ch.speaker_label,
                    )
                except (RuntimeError, ValueError) as exc:
                    set_project_status(app_engine, project_id, "error")
                    raise HTTPException(
                        status_code=502,
                        detail=f"transcription backend failed: {exc}",
                    ) from exc

            for seg in result["segments"]:
                seg["channel_id"] = ch.id
            all_segments.extend(result["segments"])

        # Stage the artifact first. If the single DB replacement transaction fails,
        # restore the previous artifact so callers retain the last-known-good pair.
        transcript_dir = project_dir / "transcript"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        result_doc = {"segments": all_segments}
        transcript_path = transcript_dir / "transcript.json"
        tmp_path = transcript_dir / "transcript.json.tmp"
        old_artifact = transcript_path.read_bytes() if transcript_path.is_file() else None
        tmp_path.write_text(json.dumps(result_doc, indent=2) + "\n")
        tmp_path.replace(transcript_path)

        try:
            with Session(app_engine) as session, session.begin():
                session.execute(
                    transcript_segments.delete().where(
                        transcript_segments.c.project_id == project_id
                    )
                )
                for seg in all_segments:
                    session.execute(
                        transcript_segments.insert().values(
                            project_id=project_id,
                            channel_id=seg["channel_id"],
                            start_ms=seg["start_ms"],
                            end_ms=seg["end_ms"],
                            text=seg["text"],
                            words_json=seg.get("words", []),
                        )
                    )
        except Exception as exc:
            restore_path = transcript_dir / "transcript.json.restore"
            if old_artifact is None:
                transcript_path.unlink(missing_ok=True)
            else:
                restore_path.write_bytes(old_artifact)
                restore_path.replace(transcript_path)
            set_project_status(app_engine, project_id, "error")
            raise HTTPException(
                status_code=500,
                detail="transcript persistence failed; previous transcript was preserved",
            ) from exc

        _check_and_update_status(project_id)
        return result_doc

    @app.post("/projects/{project_id}/transcribe")
    def transcribe_audio(project_id: str) -> dict:
        lock = _transcription_lock(project_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="transcription already in progress")
        try:
            return _transcribe_audio_locked(project_id)
        finally:
            lock.release()

    @app.post("/projects/{project_id}/segment-topics")
    def segment_topics(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)
        transcript_path = project_dir / "transcript" / "transcript.json"
        if not transcript_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="transcript.json not found — run /transcribe first",
            )

        transcript = json.loads(transcript_path.read_text())
        segments = transcript.get("segments", [])
        if not segments:
            raise HTTPException(
                status_code=400,
                detail="transcript has no segments",
            )

        from autoedit.topics import mock_segment_topics

        result = mock_segment_topics(segments)

        topics_list = result.get("topics", [])
        spans_list = result.get("spans", [])

        # Write transcript/topics.json
        transcript_dir = project_dir / "transcript"
        topics_doc = {"topics": topics_list, "spans": spans_list}
        tmp_path = transcript_dir / "topics.json.tmp"
        tmp_path.write_text(json.dumps(topics_doc, indent=2) + "\n")
        tmp_path.replace(transcript_dir / "topics.json")

        # Persist to topics + topic_spans (idempotent: delete old first)
        with Session(app_engine) as session:
            session.execute(
                topic_spans.delete().where(topic_spans.c.project_id == project_id)
            )
            session.execute(
                topics.delete().where(topics.c.project_id == project_id)
            )
            session.commit()

        label_to_topic_id: dict[str, str] = {}
        with Session(app_engine) as session:
            for t in topics_list:
                tid = new_ulid()
                label_to_topic_id[t["label"]] = tid
                session.execute(
                    topics.insert().values(
                        id=tid,
                        project_id=project_id,
                        label=t["label"],
                        colour=t["colour"],
                        description=t.get("summary", ""),
                    )
                )
            session.commit()

        with Session(app_engine) as session:
            for s in spans_list:
                tid = label_to_topic_id.get(s["label"])
                if tid is None:
                    continue
                session.execute(
                    topic_spans.insert().values(
                        topic_id=tid,
                        project_id=project_id,
                        start_ms=s["start_ms"],
                        end_ms=s["end_ms"],
                        conciseness_score=s.get("conciseness", 3),
                        summary=s.get("summary", ""),
                    )
                )
            session.commit()

        _check_and_update_status(project_id)
        return topics_doc

    @app.post("/projects/{project_id}/conciseness")
    def compute_conciseness(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        # Load topic spans and transcript
        with Session(app_engine) as session:
            span_rows = session.execute(
                select(topic_spans).where(topic_spans.c.project_id == project_id).order_by(
                    topic_spans.c.start_ms
                )
            ).all()

        if not span_rows:
            raise HTTPException(
                status_code=400,
                detail="no topic spans found — run /segment-topics first",
            )

        project_dir = project_root(app_data_root, project_id)
        transcript_path = project_dir / "transcript" / "transcript.json"
        if not transcript_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="transcript.json not found — run /transcribe first",
            )

        transcript = json.loads(transcript_path.read_text())
        segments = transcript.get("segments", [])

        # Compute median span duration
        durations = [s.end_ms - s.start_ms for s in span_rows]
        median_dur = sorted(durations)[len(durations) // 2] if durations else 1

        results = []
        for span in span_rows:
            # Gather transcript text within this span
            span_start = span.start_ms
            span_end = span.end_ms
            span_text = " ".join(
                seg["text"] for seg in segments
                if seg["start_ms"] >= span_start and seg["end_ms"] <= span_end
            )

            grade = grade_conciseness(
                current_score=span.conciseness_score or 3,
                transcript_text=span_text,
                span_dur_ms=span_end - span_start,
                median_span_dur_ms=median_dur,
            )

            # Update DB
            new_score = grade["conciseness"]
            new_summary = grade["rationale"]
            with Session(app_engine) as session:
                session.execute(
                    topic_spans.update()
                    .where(topic_spans.c.id == span.id)
                    .values(
                        conciseness_score=new_score,
                        summary=new_summary,
                    )
                )
                session.commit()

            results.append({
                "span_id": span.id,
                "start_ms": span_start,
                "end_ms": span_end,
                "conciseness": new_score,
                "filler_density": grade["filler_density"],
                "word_rate_wpm": grade["word_rate_wpm"],
                "rationale": new_summary,
            })

        _check_and_update_status(project_id)
        return {"spans": results}

    @app.post("/projects/{project_id}/summary")
    def build_project_summary(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        # Load topic_spans + topics
        with Session(app_engine) as session:
            topic_rows = session.execute(
                select(topics).where(topics.c.project_id == project_id)
            ).all()
            span_rows = session.execute(
                select(topic_spans).where(topic_spans.c.project_id == project_id).order_by(
                    topic_spans.c.start_ms
                )
            ).all()

        if not topic_rows:
            raise HTTPException(
                status_code=400,
                detail="no topics found — run /segment-topics first",
            )

        # Build topics_data with spans
        spans_by_topic: dict[str, list[dict]] = {}
        topic_labels: dict[str, str] = {}  # topic_id -> label
        topic_colours: dict[str, str] = {}
        for t in topic_rows:
            topic_labels[t.id] = t.label
            topic_colours[t.id] = t.colour
            spans_by_topic[t.id] = []

        for s in span_rows:
            if s.topic_id in spans_by_topic:
                spans_by_topic[s.topic_id].append({
                    "start_ms": s.start_ms,
                    "end_ms": s.end_ms,
                    "conciseness": s.conciseness_score or 3,
                    "summary": s.summary or "",
                })

        topics_data = [
            {
                "label": topic_labels[tid],
                "colour": topic_colours.get(tid, "#000000"),
                "spans": spans_by_topic.get(tid, []),
            }
            for tid in topic_labels
        ]

        # Load speaking_intervals with speaker labels
        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        ch_label_by_id = {ch.id: ch.speaker_label for ch in ch_rows}

        with Session(app_engine) as session:
            si_rows = session.execute(
                select(speaking_intervals).where(
                    speaking_intervals.c.channel_id.in_(
                        select(audio_channels.c.id).where(
                            audio_channels.c.project_id == project_id
                        )
                    )
                ).order_by(speaking_intervals.c.start_ms)
            ).all()

        intervals = [
            {
                "channel_id": si.channel_id,
                "speaker_label": ch_label_by_id.get(si.channel_id, "unknown"),
                "start_ms": int(si.start_ms),
                "end_ms": int(si.end_ms),
            }
            for si in si_rows
        ]

        # Load activity timeline
        activity_timeline = None
        project_dir = project_root(app_data_root, project_id)
        activity_path = project_dir / "audio" / "activity.json"
        if activity_path.is_file():
            activity_json = json.loads(activity_path.read_text())
            activity_timeline = activity_json.get("timeline")

        # Build summary
        summary = build_summary(topics_data, intervals, activity_timeline)

        # Write transcript/summary.json
        transcript_dir = project_dir / "transcript"
        tmp_path = transcript_dir / "summary.json.tmp"
        tmp_path.write_text(json.dumps(summary, indent=2) + "\n")
        tmp_path.replace(transcript_dir / "summary.json")

        _check_and_update_status(project_id)
        return summary

    @app.post("/projects/{project_id}/sub-edit-request", status_code=201)
    def nl_sub_edit_request(project_id: str, payload: dict) -> dict:
        """Natural-language sub-edit request — parses intent then delegates to sub-edit."""
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        prompt = (payload.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")

        # Load known topics
        from autoedit.nl_intent import parse_sub_edit_intent
        with Session(app_engine) as session:
            topic_rows = session.execute(
                select(topics).where(topics.c.project_id == project_id)
            ).all()
        known_topics = [t.label for t in topic_rows]

        if not known_topics:
            raise HTTPException(
                status_code=400,
                detail="no topics found in project — run /segment-topics first",
            )

        intent = parse_sub_edit_intent(prompt, known_topics)

        if not intent["confident"]:
            return {
                "status": "ambiguous",
                "reason": intent["reason"],
                "suggestions": intent.get("suggestions", known_topics[:5]),
            }

        # Delegate to the existing sub-edit endpoint
        params = intent["params"]
        name_parts = []
        if params.get("topic_labels"):
            name_parts.append(", ".join(params["topic_labels"]))
        elif params.get("exclude_labels"):
            name_parts.append("minus " + ", ".join(params["exclude_labels"]))
        elif params.get("ranges"):
            name_parts.append("custom range")
        sub_name = f'NL: {prompt[:60]}{"..." if len(prompt) > 60 else ""}'

        sub_payload = SubEditRequest(
            name=sub_name,
            mode=params["mode"],
            topic_labels=params.get("topic_labels"),
            exclude_labels=params.get("exclude_labels"),
            ranges=[TimeRange(**r) for r in params["ranges"]] if params.get("ranges") else None,
            target_duration_secs=params.get("target_duration_secs"),
        )

        # Pass through to create_sub_edit by calling it directly
        return create_sub_edit(project_id, sub_payload)

    @app.post("/projects/{project_id}/sub-edit", status_code=201)
    def create_sub_edit(project_id: str, payload: SubEditRequest) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)
        activity_path = project_dir / "audio" / "activity.json"
        if not activity_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="activity.json not found — run /activity first",
            )

        activity = json.loads(activity_path.read_text())
        timeline = activity.get("timeline", [])
        if not timeline:
            raise HTTPException(status_code=400, detail="activity timeline is empty")

        # Load topic spans
        with Session(app_engine) as session:
            span_rows = session.execute(
                select(topic_spans).where(topic_spans.c.project_id == project_id)
            ).all()

        topic_spans_list = [
            {"label": "", "start_ms": int(s.start_ms), "end_ms": int(s.end_ms),
             "conciseness": s.conciseness_score or 3}
            for s in span_rows
        ]
        # Enrich with topic labels
        with Session(app_engine) as session:
            topic_rows = session.execute(
                select(topics).where(topics.c.project_id == project_id)
            ).all()
        label_by_id = {t.id: t.label for t in topic_rows}
        for s, span_row in zip(topic_spans_list, span_rows):
            s["label"] = label_by_id.get(span_row.topic_id, "")

        # Load angle/channel data
        with Session(app_engine) as session:
            angle_rows = session.execute(
                select(angles).where(angles.c.project_id == project_id)
            ).all()
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        speaker_to_angle = _speaker_camera_map(angle_rows, ch_rows)

        sync_offsets = _rebased_sync_offsets(angle_rows, _audio_timeline_base_angle_id(ch_rows))

        wide_angle_id = None
        for a in angle_rows:
            if a.role == "wide":
                wide_angle_id = a.id
                break

        # Build custom_ranges if provided
        custom_ranges = None
        if payload.ranges:
            custom_ranges = [(r.start_ms, r.end_ms) for r in payload.ranges]

        cdl = generate_sub_edit(
            timeline,
            topic_spans_list,
            speaker_to_angle,
            sync_offsets,
            wide_angle_id=wide_angle_id,
            fps_num=project["fps_num"],
            fps_den=project["fps_den"],
            cut_params=payload.params,
            mode=payload.mode,
            labels=payload.topic_labels,
            exclude_labels=payload.exclude_labels,
            custom_ranges=custom_ranges,
        )

        if cdl is None:
            raise HTTPException(
                status_code=400,
                detail="no content selected for sub-edit",
            )

        cdl["project_id"] = project_id

        # Write edit/cdl_sub_<name>.json
        edit_dir = project_dir / "edit"
        edit_dir.mkdir(parents=True, exist_ok=True)
        safe_name = payload.name.replace("/", "_").replace(" ", "_")[:40]
        cdl_filename = f"cdl_sub_{safe_name}.json"
        tmp_path = edit_dir / f"{cdl_filename}.tmp"
        tmp_path.write_text(json.dumps(cdl, indent=2) + "\n")
        tmp_path.replace(edit_dir / cdl_filename)

        # Persist to cuts table
        cut_id = new_ulid()
        selection_params = {
            "mode": payload.mode,
            "topic_labels": payload.topic_labels,
            "exclude_labels": payload.exclude_labels,
            "ranges": [(r.start_ms, r.end_ms) for r in payload.ranges] if payload.ranges else None,
            "target_duration_secs": payload.target_duration_secs,
        }
        with Session(app_engine) as session:
            session.execute(
                cuts.insert().values(
                    id=cut_id,
                    project_id=project_id,
                    name=payload.name,
                    kind=payload.kind,
                    params_json=selection_params,
                    cdl_json=cdl,
                )
            )
            session.commit()

        return {
            "cut_id": cut_id,
            "name": payload.name,
            "kind": payload.kind,
            "cdl": cdl,
        }

    @app.post("/projects/{project_id}/titles")
    def generate_project_titles(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        project_dir = project_root(app_data_root, project_id)
        summary_path = project_dir / "transcript" / "summary.json"
        if not summary_path.is_file():
            raise HTTPException(
                status_code=400,
                detail="summary.json not found — run /summary first",
            )

        from autoedit.title_generator import generate_titles
        summary = json.loads(summary_path.read_text())
        return generate_titles(summary)

    @app.post("/projects/{project_id}/diarize")
    def diarize_speakers(project_id: str) -> dict:
        project = get_project_record(app_engine, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        with Session(app_engine) as session:
            ch_rows = session.execute(
                select(audio_channels).where(audio_channels.c.project_id == project_id)
            ).all()

        if not ch_rows:
            raise HTTPException(
                status_code=400,
                detail="no audio channels found — map channels first",
            )

        project_dir = project_root(app_data_root, project_id)
        audio_dir = project_dir / "audio"

        # If we have stereo channel mappings, use them directly
        has_stereo = (
            len(ch_rows) >= 2
            and all(ch.speaker_label not in ("mixed", "") for ch in ch_rows)
        )

        if has_stereo:
            # Stereo: speakers are already identified by channel mapping
            speakers = [
                {
                    "channel_id": ch.id,
                    "label": ch.speaker_label,
                    "source": "channel_mapping",
                }
                for ch in ch_rows
            ]
            segments = []
            # Build mock segments alternating between speakers for a 10s clip
            dur = 10000
            seg_len = 2000
            pos = 0
            speaker_idx = 0
            while pos < dur:
                end = min(pos + seg_len, dur)
                segments.append({
                    "speaker": speakers[speaker_idx % len(speakers)]["label"],
                    "start_ms": pos,
                    "end_ms": end,
                })
                pos = end
                speaker_idx += 1
        else:
            # Mono: run diarization on the mixed track
            wav_path = None
            for ch in ch_rows:
                maybe_path = audio_dir / (ch.wav_path or "").split("/")[-1]
                if maybe_path.is_file():
                    wav_path = maybe_path
                    break

            if wav_path is None:
                raise HTTPException(
                    status_code=400,
                    detail="no WAV file found for diarization",
                )

            import wave as _wave
            with _wave.open(str(wav_path), "rb") as wf:
                framerate = wf.getframerate()
                nframes = wf.getnframes()

            segs = mock_diarize(framerate, duration_samples=nframes)

            # Create audio_channels rows for each discovered speaker
            unique_speakers = sorted(set(s["speaker"] for s in segs))
            speakers = []
            for spk_label in unique_speakers:
                ch_id = new_ulid()
                with Session(app_engine) as session:
                    session.execute(
                        audio_channels.insert().values(
                            id=ch_id,
                            project_id=project_id,
                            speaker_label=spk_label,
                            source_angle_id=ch_rows[0].source_angle_id,
                            channel_index=0,
                        )
                    )
                    session.commit()
                speakers.append({
                    "channel_id": ch_id,
                    "label": spk_label,
                    "source": "diarization",
                })

            segments = segs

        # Write diarization.json
        result = {
            "speakers": speakers,
            "segments": segments,
            "mode": "channel_mapping_placeholder" if has_stereo else "mock_diarization",
            "is_mock": True,
        }
        diarize_path = audio_dir / "diarization.json"
        tmp_path = audio_dir / "diarization.json.tmp"
        tmp_path.write_text(json.dumps(result, indent=2) + "\n")
        tmp_path.replace(diarize_path)

        _check_and_update_status(project_id)
        return result

    return app


app = create_app()
