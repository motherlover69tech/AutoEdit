from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from autoedit.db.schema import angles
from autoedit.project_paths import is_ulid, project_root
from autoedit.projects import get_project, new_ulid

AngleRole = Literal["cam_left", "cam_right", "wide", "other"]


class UploadError(ValueError):
    pass


class UploadNotFoundError(FileNotFoundError):
    pass


def safe_source_filename(filename: str) -> str:
    if not filename or filename in {".", ".."}:
        raise UploadError("invalid filename")
    path = Path(filename)
    if path.name != filename or any(part in {".", ".."} for part in path.parts):
        raise UploadError("invalid filename")
    return filename


def upload_root(data_root: str | Path, project_id: str, upload_id: str) -> Path:
    # Both ids must be ULID-shaped, confining the temp path under DATA_ROOT.
    project_dir = project_root(data_root, project_id)
    upload_dir = project_root(project_dir / ".uploads", upload_id)
    return upload_dir


def _part_path(upload_dir: Path, index: int) -> Path:
    return upload_dir / "chunks" / f"{index:08d}.part"


def _metadata_path(upload_dir: Path) -> Path:
    return upload_dir / "metadata.json"


def _read_metadata(upload_dir: Path) -> dict[str, Any]:
    try:
        return json.loads(_metadata_path(upload_dir).read_text())
    except FileNotFoundError as exc:
        raise UploadNotFoundError("upload not found") from exc


def _write_metadata(upload_dir: Path, metadata: dict[str, Any]) -> None:
    tmp_path = upload_dir / "metadata.json.tmp"
    tmp_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(_metadata_path(upload_dir))


def highest_contiguous_chunk(upload_dir: Path, total_chunks: int) -> int:
    chunks_dir = upload_dir / "chunks"
    highest = -1
    for index in range(total_chunks):
        if not _part_path(upload_dir, index).is_file():
            break
        highest = index
    return highest


def create_upload(
    engine: Engine,
    data_root: str | Path,
    *,
    project_id: str,
    filename: str,
    label: str,
    role: AngleRole,
    total_bytes: int,
    total_chunks: int,
    chunk_bytes: int | None = None,
) -> dict[str, Any]:
    if get_project(engine, project_id) is None:
        raise UploadNotFoundError("project not found")
    safe_filename = safe_source_filename(filename)
    if total_bytes <= 0:
        raise UploadError("total_bytes must be positive")
    if total_chunks <= 0:
        raise UploadError("total_chunks must be positive")
    if chunk_bytes is not None and chunk_bytes <= 0:
        raise UploadError("chunk_bytes must be positive")

    upload_id = new_ulid()
    upload_dir = upload_root(data_root, project_id, upload_id)
    (upload_dir / "chunks").mkdir(parents=True, exist_ok=False)
    metadata = {
        "upload_id": upload_id,
        "project_id": project_id,
        "filename": safe_filename,
        "label": label,
        "role": role,
        "total_bytes": total_bytes,
        "total_chunks": total_chunks,
        "chunk_bytes": chunk_bytes,
    }
    _write_metadata(upload_dir, metadata)
    return {**metadata, "highest_contiguous_chunk": -1}


def get_upload_status(data_root: str | Path, upload_id: str, *, project_id: str | None = None) -> dict[str, Any]:
    upload_dir, metadata = find_upload(data_root, upload_id, project_id=project_id)
    return {
        **metadata,
        "highest_contiguous_chunk": highest_contiguous_chunk(upload_dir, metadata["total_chunks"]),
    }


def find_upload(
    data_root: str | Path,
    upload_id: str,
    *,
    project_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    if not is_ulid(upload_id):
        raise UploadError("invalid upload_id")

    if project_id is not None:
        upload_dir = upload_root(data_root, project_id, upload_id)
        metadata = _read_metadata(upload_dir)
        return upload_dir, metadata

    # Upload ids are not globally indexed in DB yet; find the matching project temp dir.
    root = Path(data_root)
    for metadata_path in root.glob(f"*/.uploads/{upload_id}/metadata.json"):
        upload_dir = metadata_path.parent
        return upload_dir, _read_metadata(upload_dir)
    raise UploadNotFoundError("upload not found")


def write_chunk(data_root: str | Path, upload_id: str, index: int, content: bytes) -> dict[str, Any]:
    upload_dir, metadata = find_upload(data_root, upload_id)
    if index < 0 or index >= metadata["total_chunks"]:
        raise UploadError("chunk index out of range")

    chunks_dir = upload_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = chunks_dir / f"{index:08d}.part.tmp"
    tmp_path.write_bytes(content)
    tmp_path.replace(_part_path(upload_dir, index))

    chunk_bytes = metadata.get("chunk_bytes")
    if chunk_bytes:
        assembled_path = upload_dir / "assembled.tmp"
        offset = index * int(chunk_bytes)
        with assembled_path.open("r+b" if assembled_path.exists() else "w+b") as assembled:
            assembled.seek(offset)
            assembled.write(content)
    return get_upload_status(data_root, upload_id)


def complete_upload(
    engine: Engine,
    data_root: str | Path,
    *,
    upload_id: str,
    expected_sha256: str | None = None,
    expected_total_bytes: int,
) -> dict[str, Any]:
    upload_dir, metadata = find_upload(data_root, upload_id)
    if highest_contiguous_chunk(upload_dir, metadata["total_chunks"]) != metadata["total_chunks"] - 1:
        raise UploadError("upload is missing chunks")
    if expected_total_bytes != metadata["total_bytes"]:
        raise UploadError("byte count mismatch")

    assembled_path = upload_dir / "assembled.tmp"
    if not assembled_path.is_file():
        with assembled_path.open("wb") as out_file:
            for index in range(metadata["total_chunks"]):
                part = _part_path(upload_dir, index)
                with part.open("rb") as in_file:
                    shutil.copyfileobj(in_file, out_file, length=1024 * 1024)

    total_bytes = assembled_path.stat().st_size
    if total_bytes != expected_total_bytes:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise UploadError("byte count mismatch")

    computed_sha256 = None
    if expected_sha256 is not None:
        digest = hashlib.sha256()
        with assembled_path.open("rb") as in_file:
            for chunk in iter(lambda: in_file.read(1024 * 1024), b""):
                digest.update(chunk)
        computed_sha256 = digest.hexdigest()
        if computed_sha256 != expected_sha256:
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise UploadError("sha256 mismatch")

    project_dir = project_root(data_root, metadata["project_id"])
    source_dir = project_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    target_path = source_dir / metadata["filename"]
    if target_path.exists():
        raise UploadError("source file already exists")
    assembled_path.replace(target_path)
    shutil.rmtree(upload_dir, ignore_errors=True)

    angle_id = new_ulid()
    source_path = f"source/{metadata['filename']}"
    with Session(engine) as session:
        session.execute(
            angles.insert().values(
                id=angle_id,
                project_id=metadata["project_id"],
                label=metadata["label"],
                role=metadata["role"],
                source_path=source_path,
                sync_offset_ms=0,
            )
        )
        session.commit()
        row = session.execute(select(angles).where(angles.c.id == angle_id)).one()._mapping

    return {
        "id": row.id,
        "project_id": row.project_id,
        "label": row.label,
        "role": row.role,
        "source_path": row.source_path,
        "proxy_path": row.proxy_path,
        "proxy_low_path": row.proxy_low_path,
        "duration_ms": row.duration_ms,
        "sync_offset_ms": row.sync_offset_ms,
        "src_fps_num": row.src_fps_num,
        "src_fps_den": row.src_fps_den,
        "width": row.width,
        "height": row.height,
        "vcodec": row.vcodec,
        "sha256": computed_sha256,
    }
