from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    func,
)

# BigInteger that works as autoincrement on both SQLite (as INTEGER) and MySQL.
BigIntPK = Integer().with_variant(BigInteger(), "mysql")

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", String(26), primary_key=True),
    Column("username", String(120), unique=True, nullable=False),
    Column("pw_hash", String(255), nullable=False),
    Column("display_name", String(120), nullable=False),
    Column("role", Enum("admin", "reviewer", name="user_role"), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

projects = Table(
    "projects",
    metadata,
    Column("id", String(26), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("status", Enum("created", "ingesting", "processing", "ready", "error", name="project_status"), nullable=False),
    Column("fps_num", Integer, nullable=False),
    Column("fps_den", Integer, nullable=False),
    Column("timeline_origin_ms", BigInteger, nullable=False, server_default="0"),
    Column("config_json", JSON, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now(), onupdate=func.now()),
    CheckConstraint("fps_num > 0", name="ck_projects_fps_num_positive"),
    CheckConstraint("fps_den > 0", name="ck_projects_fps_den_positive"),
)

angles = Table(
    "angles",
    metadata,
    Column("id", String(26), primary_key=True),
    Column("project_id", String(26), ForeignKey("projects.id"), nullable=False),
    Column("label", String(64), nullable=False),
    Column("role", Enum("cam_left", "cam_right", "wide", "other", name="angle_role"), nullable=False),
    Column("source_path", String(512), nullable=False),
    Column("proxy_path", String(512)),
    Column("proxy_low_path", String(512)),
    Column("duration_ms", BigInteger),
    Column("sync_offset_ms", BigInteger, nullable=False, server_default="0"),
    Column("src_fps_num", Integer),
    Column("src_fps_den", Integer),
    Column("width", Integer),
    Column("height", Integer),
    Column("vcodec", String(32)),
)

audio_channels = Table(
    "audio_channels",
    metadata,
    Column("id", String(26), primary_key=True),
    Column("project_id", String(26), ForeignKey("projects.id"), nullable=False),
    Column("speaker_label", String(64), nullable=False),
    Column("source_angle_id", String(26), ForeignKey("angles.id"), nullable=False),
    Column("channel_index", Integer, nullable=False),
    Column("wav_path", String(512)),
    Column("noise_floor_db", Float),
    Column("vad_threshold_db", Float),
)

speaking_intervals = Table(
    "speaking_intervals",
    metadata,
    Column("id", BigIntPK, primary_key=True, autoincrement=True),
    Column("channel_id", String(26), ForeignKey("audio_channels.id"), nullable=False),
    Column("start_ms", BigInteger, nullable=False),
    Column("end_ms", BigInteger, nullable=False),
    Column("mean_db", Float),
    Column("peak_db", Float),
    Index("ix_speaking_intervals_channel_start", "channel_id", "start_ms"),
)

transcript_segments = Table(
    "transcript_segments",
    metadata,
    Column("id", BigIntPK, primary_key=True, autoincrement=True),
    Column("project_id", String(26), ForeignKey("projects.id"), nullable=False),
    Column("channel_id", String(26), ForeignKey("audio_channels.id"), nullable=False),
    Column("start_ms", BigInteger, nullable=False),
    Column("end_ms", BigInteger, nullable=False),
    Column("text", Text, nullable=False),
    Column("words_json", JSON),
    Index("ix_transcript_segments_project_start", "project_id", "start_ms"),
)

topics = Table(
    "topics",
    metadata,
    Column("id", String(26), primary_key=True),
    Column("project_id", String(26), ForeignKey("projects.id"), nullable=False),
    Column("label", String(255), nullable=False),
    Column("colour", String(7), nullable=False),
    Column("description", Text),
)

topic_spans = Table(
    "topic_spans",
    metadata,
    Column("id", BigIntPK, primary_key=True, autoincrement=True),
    Column("topic_id", String(26), ForeignKey("topics.id"), nullable=False),
    Column("project_id", String(26), ForeignKey("projects.id"), nullable=False),
    Column("start_ms", BigInteger, nullable=False),
    Column("end_ms", BigInteger, nullable=False),
    Column("conciseness_score", Integer, nullable=False),
    Column("summary", Text),
    Index("ix_topic_spans_project_start", "project_id", "start_ms"),
    CheckConstraint("conciseness_score >= 1 AND conciseness_score <= 5", name="ck_topic_spans_conciseness"),
)

cuts = Table(
    "cuts",
    metadata,
    Column("id", String(26), primary_key=True),
    Column("project_id", String(26), ForeignKey("projects.id"), nullable=False),
    Column("name", String(255), nullable=False),
    Column("kind", Enum("rough", "themed", "social", "manual", name="cut_kind"), nullable=False),
    Column("params_json", JSON, nullable=False),
    Column("cdl_json", JSON, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

notes = Table(
    "notes",
    metadata,
    Column("id", BigIntPK, primary_key=True, autoincrement=True),
    Column("project_id", String(26), ForeignKey("projects.id"), nullable=False),
    Column("cut_id", String(26), ForeignKey("cuts.id")),
    Column("t_ms", BigInteger, nullable=False),
    Column("author", String(120), nullable=False),
    Column("body", Text, nullable=False),
    Column("kind", Enum("note", "cut_suggestion", name="note_kind"), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Index("ix_notes_project_t", "project_id", "t_ms"),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(26), primary_key=True),
    Column("project_id", String(26), ForeignKey("projects.id"), nullable=False),
    Column("type", String(40), nullable=False),
    Column("state", Enum("queued", "running", "done", "error", name="job_state"), nullable=False),
    Column("progress", Integer, nullable=False, server_default="0"),
    Column("message", Text),
    Column("payload_json", JSON),
    Column("error_text", Text),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
)
