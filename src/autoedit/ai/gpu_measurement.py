"""Offline, bounded GPU acceptance measurement helpers.

This module does not query a host or mutate Docker.  It validates sanitized
sampler records captured by an approved acceptance harness and calculates the
AI-GPU-1 headroom verdict deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class GPUSample:
    timestamp_ms: int
    total_mib: int
    used_mib: int
    phase: str
    processes: tuple[str, ...] = ()

    @property
    def free_mib(self) -> int:
        return self.total_mib - self.used_mib


def validate_sampling(samples: Iterable[GPUSample], *, max_interval_ms: int = 500) -> tuple[GPUSample, ...]:
    """Validate monotonic samples and reject gaps larger than the gate allows."""
    ordered = tuple(samples)
    if not ordered:
        raise ValueError("at least one GPU sample is required")
    for sample in ordered:
        if sample.total_mib <= 0 or sample.used_mib < 0 or sample.used_mib > sample.total_mib:
            raise ValueError("GPU sample memory values are invalid")
        if not sample.phase:
            raise ValueError("GPU sample phase is required")
    for previous, current in zip(ordered, ordered[1:]):
        gap = current.timestamp_ms - previous.timestamp_ms
        if gap <= 0:
            raise ValueError("GPU sample timestamps must increase")
        if gap > max_interval_ms:
            raise ValueError(f"GPU sampler gap exceeds {max_interval_ms} ms")
    return ordered


def summarize_gpu_acceptance(
    samples: Iterable[GPUSample],
    *,
    required_headroom_mib: int = 2048,
    unknown_processes: bool = False,
    workload_failures: Iterable[str] = (),
) -> dict[str, object]:
    """Return a redaction-safe acceptance summary; no paths or process IDs."""
    checked = validate_sampling(samples)
    total = checked[0].total_mib
    if any(sample.total_mib != total for sample in checked):
        raise ValueError("GPU total memory changed during measurement")
    peak = max(checked, key=lambda sample: sample.used_mib)
    minimum_free = min(sample.free_mib for sample in checked)
    threshold = max(required_headroom_mib, (total + 9) // 10)
    failures = tuple(str(item) for item in workload_failures if item)
    verdict = not unknown_processes and not failures and minimum_free >= threshold
    return {
        "verdict": "PASS" if verdict else "FAIL",
        "total_mib": total,
        "peak_used_mib": peak.used_mib,
        "minimum_free_mib": minimum_free,
        "required_headroom_mib": threshold,
        "peak_phase": peak.phase,
        "sample_count": len(checked),
        "unknown_processes": bool(unknown_processes),
        "workload_failures": list(failures),
    }


__all__ = ["GPUSample", "summarize_gpu_acceptance", "validate_sampling"]
