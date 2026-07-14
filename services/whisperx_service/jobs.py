"""Single-concurrency in-process queue for the isolated GPU worker.

The main AUTOEDIT API remains responsible for durable project job records. This
queue only prevents concurrent model execution/OOM inside one worker process.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class JobNotFoundError(LookupError):
    pass


class GPUJobQueueFull(RuntimeError):
    """Raised when the bounded GPU work queue has no capacity."""


class GPUJobManager:
    def __init__(
        self,
        runner: Callable[[Any], dict[str, Any]],
        *,
        max_pending: int = 8,
        max_history: int = 100,
    ):
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        if max_history <= 0:
            raise ValueError("max_history must be positive")
        self._runner = runner
        self._max_pending = max_pending
        self._max_history = max_history
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisperx-gpu")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._futures: dict[str, Future] = {}

    def submit(self, request: Any) -> dict[str, Any]:
        job_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._prune_terminal_history_locked()
            pending = sum(
                job["state"] in {"queued", "running"} for job in self._jobs.values()
            )
            if pending >= self._max_pending:
                raise GPUJobQueueFull("WhisperX analysis queue is full")
            self._jobs[job_id] = {
                "job_id": job_id,
                "state": "queued",
                "stage": "queued",
                "progress": 0,
                "created_at": now,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "cancel_requested": False,
            }
            future = self._executor.submit(self._execute, job_id, request)
            self._futures[job_id] = future
            return self._public(self._jobs[job_id])

    def _prune_terminal_history_locked(self) -> None:
        terminal_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job["state"] in {"done", "failed", "cancelled"}
        ]
        while len(self._jobs) >= self._max_history and terminal_ids:
            job_id = terminal_ids.pop(0)
            self._jobs.pop(job_id, None)
            self._futures.pop(job_id, None)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return self._public(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            if job["state"] in {"done", "failed", "cancelled"}:
                return self._public(job)
            job["cancel_requested"] = True
            future = self._futures.get(job_id)
            if job["state"] == "queued" and future is not None and future.cancel():
                self._mark_cancelled(job)
            return self._public(job)

    def _execute(self, job_id: str, request: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job["cancel_requested"]:
                self._mark_cancelled(job)
                return
            job.update(
                state="running",
                stage="analysis",
                progress=10,
                started_at=datetime.now(UTC).isoformat(),
            )
        try:
            result = self._runner(request)
        except Exception:
            logger.exception("WhisperX queued analysis failed for job %s", job_id)
            with self._lock:
                job = self._jobs[job_id]
                if job["cancel_requested"]:
                    self._mark_cancelled(job)
                else:
                    job.update(
                        state="failed",
                        stage="failed",
                        progress=100,
                        error={
                            "code": "analysis_failed",
                            "message": "WhisperX analysis failed",
                        },
                        finished_at=datetime.now(UTC).isoformat(),
                    )
            return

        with self._lock:
            job = self._jobs[job_id]
            if job["cancel_requested"]:
                self._mark_cancelled(job)
            else:
                job.update(
                    state="done",
                    stage="completed",
                    progress=100,
                    result=result,
                    finished_at=datetime.now(UTC).isoformat(),
                )

    @staticmethod
    def _mark_cancelled(job: dict[str, Any]) -> None:
        job.update(
            state="cancelled",
            stage="cancelled",
            progress=100,
            result=None,
            error=None,
            finished_at=datetime.now(UTC).isoformat(),
        )

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in job.items() if key != "cancel_requested"}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
