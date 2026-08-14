"""Observe Dots long-form completion from output-file publication."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DotsOutputObserver:
    """Require a post-submit output mtime that is stable across two polls.

    Dots may report API ``completed`` while long-form WAV assembly is still in
    progress. The first observation records a new file generation; the second
    identical observation establishes that assembly stopped changing.
    """

    output_path: Path
    submitted_after_mtime_ns: int = 0
    completed_at_mtime_ns: int | None = None
    _candidate_mtime_ns: int | None = None
    _candidate_size: int | None = None

    def observe(self, *, api_status: str) -> bool:
        if api_status != "completed":
            self._candidate_mtime_ns = None
            self._candidate_size = None
            return False
        try:
            info = self.output_path.stat()
        except OSError:
            return False
        if not self.output_path.is_file() or info.st_size <= 0:
            return False
        if info.st_mtime_ns <= self.submitted_after_mtime_ns:
            return False
        current = (info.st_mtime_ns, info.st_size)
        if current != (self._candidate_mtime_ns, self._candidate_size):
            self._candidate_mtime_ns, self._candidate_size = current
            return False
        self.completed_at_mtime_ns = info.st_mtime_ns
        return True


__all__ = ["DotsOutputObserver"]
