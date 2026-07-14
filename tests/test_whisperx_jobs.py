from __future__ import annotations

import threading
import time

import pytest

from services.whisperx_service.jobs import (
    GPUJobManager,
    GPUJobQueueFull,
    JobNotFoundError,
)


def _wait_for(manager: GPUJobManager, job_id: str, state: str, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job["state"] == state:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {state}: {manager.get(job_id)}")


def test_gpu_jobs_run_one_at_a_time_and_second_job_queues():
    first_started = threading.Event()
    release_first = threading.Event()
    calls = []

    def runner(value):
        calls.append(value)
        if value == "first":
            first_started.set()
            assert release_first.wait(2)
        return {"value": value}

    manager = GPUJobManager(runner)
    try:
        first = manager.submit("first")
        assert first_started.wait(1)
        second = manager.submit("second")

        assert manager.get(first["job_id"])["state"] == "running"
        assert manager.get(second["job_id"])["state"] == "queued"
        assert calls == ["first"]

        release_first.set()
        assert _wait_for(manager, first["job_id"], "done")["result"] == {"value": "first"}
        assert _wait_for(manager, second["job_id"], "done")["result"] == {"value": "second"}
    finally:
        release_first.set()
        manager.shutdown()


def test_queued_job_can_be_cancelled_without_running():
    first_started = threading.Event()
    release_first = threading.Event()
    calls = []

    def runner(value):
        calls.append(value)
        if value == "first":
            first_started.set()
            assert release_first.wait(2)
        return {"value": value}

    manager = GPUJobManager(runner)
    try:
        manager.submit("first")
        assert first_started.wait(1)
        second = manager.submit("second")

        cancelled = manager.cancel(second["job_id"])

        assert cancelled["state"] == "cancelled"
        release_first.set()
        time.sleep(0.05)
        assert calls == ["first"]
    finally:
        release_first.set()
        manager.shutdown()


def test_job_failure_is_log_safe_and_does_not_expose_exception_message():
    def runner(_value):
        raise RuntimeError("secret path /data/private/interview.wav")

    manager = GPUJobManager(runner)
    try:
        job = manager.submit("bad")
        failed = _wait_for(manager, job["job_id"], "failed")

        assert failed["error"] == {
            "code": "analysis_failed",
            "message": "WhisperX analysis failed",
        }
        assert "/data/private" not in str(failed)
    finally:
        manager.shutdown()


def test_gpu_job_queue_rejects_work_above_pending_limit():
    started = threading.Event()
    release = threading.Event()

    def runner(value):
        started.set()
        assert release.wait(2)
        return {"value": value}

    manager = GPUJobManager(runner, max_pending=1)
    try:
        manager.submit("first")
        assert started.wait(1)

        with pytest.raises(GPUJobQueueFull, match="queue is full"):
            manager.submit("second")
    finally:
        release.set()
        manager.shutdown()


def test_gpu_job_manager_prunes_old_terminal_history():
    manager = GPUJobManager(lambda value: {"value": value}, max_history=2)
    try:
        first = manager.submit("first")
        _wait_for(manager, first["job_id"], "done")
        second = manager.submit("second")
        _wait_for(manager, second["job_id"], "done")
        third = manager.submit("third")
        _wait_for(manager, third["job_id"], "done")

        with pytest.raises(JobNotFoundError):
            manager.get(first["job_id"])
        assert manager.get(second["job_id"])["state"] == "done"
        assert manager.get(third["job_id"])["state"] == "done"
    finally:
        manager.shutdown()
