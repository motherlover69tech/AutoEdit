"""ffmpeg execution with a stall watchdog instead of a fixed total timeout.

Fixed total timeouts (e.g. the old timeout=600 on channel extraction) fail
on long media: extracting audio from a 90-minute source on a busy Unraid
share can legitimately take longer than any fixed number, while a genuinely
stalled encode should be killed in minutes. ffmpeg emits progress lines
continuously (`-progress pipe:1`), so the correct policy is: no total time
limit, but kill the process if it stops making progress for stall_timeout
seconds.
"""
from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from typing import Sequence


class FfmpegStalledError(RuntimeError):
    """Raised when ffmpeg stops reporting progress for too long."""


def run_ffmpeg_watchdog(
    cmd: Sequence[str],
    *,
    stall_timeout: float = 180.0,
) -> subprocess.CompletedProcess:
    """Run an ffmpeg command, killing it only if progress stalls.

    Injects ``-nostdin -progress pipe:1 -nostats`` after the executable so
    ffmpeg reports progress on stdout roughly twice a second. The watchdog
    resets on every progress line; a long job on slow storage keeps running
    for hours if needed, while a hung process (dead GPU encoder, unreachable
    NFS mount, deadlocked filter graph) is killed after ``stall_timeout``
    seconds of silence.

    Returns a CompletedProcess with returncode and captured stderr (tail),
    matching what callers previously got from subprocess.run.
    """
    argv = [cmd[0], "-nostdin", "-progress", "pipe:1", "-nostats", *cmd[1:]]

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        # Preserve the exact error contract callers already handle/test.
        raise FileNotFoundError(exc.errno, "ffmpeg executable not found") from exc

    last_activity = time.monotonic()
    lock = threading.Lock()
    # Keep only the tail of stderr: ffmpeg errors appear at the end, and
    # unbounded capture of a chatty 90-minute encode wastes memory.
    stderr_tail: deque[str] = deque(maxlen=200)

    def _touch() -> None:
        nonlocal last_activity
        with lock:
            last_activity = time.monotonic()

    def _drain_stdout() -> None:
        assert proc.stdout is not None
        for _line in proc.stdout:
            _touch()

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line)
            _touch()

    threads = [
        threading.Thread(target=_drain_stdout, daemon=True),
        threading.Thread(target=_drain_stderr, daemon=True),
    ]
    for t in threads:
        t.start()

    while True:
        rc = proc.poll()
        if rc is not None:
            break
        with lock:
            silent_for = time.monotonic() - last_activity
        if silent_for > stall_timeout:
            proc.kill()
            proc.wait()
            raise FfmpegStalledError(
                f"ffmpeg made no progress for {int(silent_for)}s and was killed "
                f"(stall watchdog, limit {int(stall_timeout)}s). Command: {' '.join(cmd[:6])}…"
            )
        time.sleep(0.5)

    for t in threads:
        t.join(timeout=5)

    return subprocess.CompletedProcess(
        args=list(argv),
        returncode=proc.returncode,
        stdout="",
        stderr="".join(stderr_tail),
    )
