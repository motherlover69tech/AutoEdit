"""Failure-safe persistence for versioned AI artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from autoedit.ai.contracts import AIResultArtifact, FailedRunArtifact


class ArtifactIntegrityError(ValueError):
    """Raised when an artifact does not match its declared source inputs."""


class AIArtifactStore:
    """Store immutable runs and a replaceable last-known-good result pointer.

    A failed or malformed run is recorded separately and never replaces
    ``result.json``. Publication verifies all declared input hashes before any
    durable result is written.
    """

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.root = self.project_dir / "audio" / "ai" / "v1"

    @property
    def result_path(self) -> Path:
        return self.root / "result.json"

    def publish(self, artifact: AIResultArtifact) -> Path:
        artifact = AIResultArtifact.model_validate(artifact)
        self._verify_inputs(artifact)
        payload = artifact.model_dump(mode="json")
        run_path = self.root / "runs" / f"{artifact.run_id}.json"

        self._validate_output_path(run_path)
        self._validate_output_path(self.result_path)
        try:
            exclusive_write_json(run_path, payload)
        except FileExistsError:
            existing = AIResultArtifact.model_validate_json(run_path.read_text(encoding="utf-8"))
            if existing != artifact:
                raise ArtifactIntegrityError(
                    f"run_id {artifact.run_id!r} already exists with different content"
                )

        atomic_write_json(self.result_path, payload)
        return self.result_path

    def load_last_good(self) -> AIResultArtifact | None:
        if not self.result_path.is_file():
            return None
        return AIResultArtifact.model_validate_json(
            self.result_path.read_text(encoding="utf-8")
        )

    def record_failure(
        self,
        *,
        run_id: str,
        stage: str,
        error_code: str,
        message: str,
    ) -> Path:
        failure = FailedRunArtifact(
            run_id=run_id,
            created_at=datetime.now(UTC),
            stage=stage,
            error_code=error_code,
            message=message,
        )
        path = self.root / "failures" / f"{failure.run_id}.json"
        self._validate_output_path(path)
        try:
            exclusive_write_json(path, failure.model_dump(mode="json"))
        except FileExistsError as exc:
            raise ArtifactIntegrityError(
                f"failure run_id {failure.run_id!r} already exists"
            ) from exc
        return path

    def _verify_inputs(self, artifact: AIResultArtifact) -> None:
        declared = [
            (source.relative_path, source.sha256)
            for source in artifact.sources
        ]
        declared.append((artifact.analysis_audio.relative_path, artifact.analysis_audio.sha256))
        for relative_path, expected_hash in declared:
            path = self._resolve_project_path(relative_path)
            if not path.is_file():
                raise ArtifactIntegrityError(f"declared input does not exist: {relative_path}")
            actual_hash = sha256_file(path)
            if actual_hash != expected_hash:
                raise ArtifactIntegrityError(f"input hash mismatch: {relative_path}")

    def _resolve_project_path(self, relative_path: str) -> Path:
        candidate = (self.project_dir / relative_path).resolve()
        if not candidate.is_relative_to(self.project_dir):
            raise ArtifactIntegrityError("artifact path escapes project root")
        return candidate

    def _validate_output_path(self, path: Path) -> None:
        """Reject output paths redirected outside the project by symlink parents."""
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self.project_dir):
            raise ArtifactIntegrityError("output path escapes project root")


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def exclusive_write_json(path: Path, payload: dict) -> None:
    """Create immutable JSON without an exists-then-replace race."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link creates the final name atomically and fails if it exists.
        os.link(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)
