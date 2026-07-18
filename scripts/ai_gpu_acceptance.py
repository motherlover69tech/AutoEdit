#!/usr/bin/env python3
"""Sanitized, offline-first AI-GPU-1 acceptance harness.

No command, HTTP request, container operation, or GPU query is performed by
``--mock`` (the default).  Live execution is deliberately not implemented in
this safe harness; a future adapter must require explicit authorization and
read-only discovery before it can be enabled.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

REQUIRED_PHASES = ("baseline", "resident", "cold", "active", "active_repeat", "post")
SECRET_RE = re.compile(r"(?i)(token|password|secret|cookie|authorization|api[_-]?key|credential)\s*[=:]\s*[^\s,;]+")
URL_SECRET_RE = re.compile(r"(?i)(https?://)([^/@\s]+):([^/@\s]+)@")
# Bounded allowlist for discovery output (BUG-AIGPU1-002).  Raw command stdout
# can contain private paths, transcript text, person names, and runtime IDs; it
# must never enter evidence.  These patterns are stripped/redacted first.
PRIVATE_PATH_RE = re.compile(r"(?<![\w./-])(/[^ \t\n\r\f\v]+|(?:[A-Za-z]:\\)[^ \t\n\r\f\v]+)")
RUNTIME_ID_RE = re.compile(r"(?i)\b(?:runtime-id|run-id|container-id|proc-id|pid)[-_ ]?[=:]?[ -]?[\w-]{2,}")
TRANSCRIPT_FRAGMENT_RE = re.compile(r"transcript[=:]?\s*[^\s]{2,}")


class AcceptanceFailure(ValueError):
    """A visible, fail-closed acceptance error."""


def _safe_scalar(value: Any) -> Any:
    """Return a redacted placeholder for any non-allowlisted string.

    Discovery output must never carry private paths, transcript fragments,
    person names, runtime IDs, secrets, or media-like filenames.  Only opaque,
    non-sensitive tokens (gpu model names, numeric ids, statuses) survive.
    """
    if isinstance(value, str):
        redacted = PRIVATE_PATH_RE.sub("[REDACTED-PATH]", value)
        redacted = RUNTIME_ID_RE.sub("[REDACTED-ID]", redacted)
        redacted = TRANSCRIPT_FRAGMENT_RE.sub("transcript=[REDACTED]", redacted)
        redacted = SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", URL_SECRET_RE.sub(r"\1[REDACTED]@", redacted))
        return redacted
    return value


def sanitize(value: Any) -> Any:
    """Recursively redact secret-bearing keys/URLs and private discovery strings."""
    if isinstance(value, Mapping):
        return {str(k): sanitize(v) for k, v in value.items()
                if not re.search(r"(?i)(token|password|secret|cookie|credential|authorization|api[_-]?key)", str(k))}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return _safe_scalar(value)


redact = sanitize  # backwards-compatible public name

@dataclass(frozen=True)
class ProcessUsage:
    pid: int
    name: str
    used_mib: int


@dataclass(frozen=True)
class Sample:
    timestamp_ms: int
    total_mib: int
    used_mib: int
    phase: str
    processes: tuple[ProcessUsage, ...] = ()
    wall_timestamp_ms: int | None = None

    @property
    def free_mib(self) -> int:
        return self.total_mib - self.used_mib


@dataclass(frozen=True)
class PhaseConfig:
    baseline_seconds: int = 10
    post_seconds: int = 30
    sample_interval_ms: int = 250


class AcceptanceAdapter(Protocol):
    """Side-effect boundary; production adapters must be injected explicitly."""

    def check(self, name: str) -> bool: ...


@dataclass
class MockAdapter:
    """Deterministic adapter used by tests and the CLI's offline mode."""

    checks: dict[str, bool] = field(default_factory=lambda: {name: True for name in (
        "app", "dots", "worker_ready", "ollama_unloaded", "outputs", "cleanup", "restarts"
    )})

    def check(self, name: str) -> bool:
        return self.checks.get(name, False)


class AcceptanceHarness:
    """Run deterministic phases through an injectable, side-effect-free adapter."""

    def __init__(self, adapter: AcceptanceAdapter | None = None, *, config: PhaseConfig | None = None) -> None:
        self.adapter = adapter or MockAdapter()
        self.config = config or PhaseConfig()

    def run(self) -> dict[str, Any]:
        evidence = mock_evidence(config=self.config)
        evidence["health"].update(
            app=self.adapter.check("app"), dots=self.adapter.check("dots"),
            worker_ready=self.adapter.check("worker_ready"),
            ollama_unloaded=self.adapter.check("ollama_unloaded"),
            restarts=0 if self.adapter.check("restarts") else 1,
        )
        if not self.adapter.check("outputs"):
            evidence["outputs"] = {key: False for key in evidence["outputs"]}
        if not self.adapter.check("cleanup"):
            evidence["cleanup"] = {"memory_drift_mib": 513, "app_healthy": False}
        return validate_acceptance(evidence, config=self.config)


def validate_samples(samples: Iterable[Sample], *, nominal_interval_ms: int = 250, max_gap_ms: int = 500) -> tuple[Sample, ...]:
    ordered = tuple(samples)
    if not ordered:
        raise AcceptanceFailure("at least one GPU sample is required")
    if nominal_interval_ms <= 0 or nominal_interval_ms > 250:
        raise AcceptanceFailure("nominal GPU sampling interval must be <= 250 ms")
    for sample in ordered:
        if sample.timestamp_ms < 0 or sample.total_mib <= 0 or not 0 <= sample.used_mib <= sample.total_mib:
            raise AcceptanceFailure("invalid GPU memory sample")
        if not sample.phase:
            raise AcceptanceFailure("missing GPU sample phase")
        if sample.wall_timestamp_ms is not None and sample.wall_timestamp_ms < 0:
            raise AcceptanceFailure("invalid wall clock sample")
        for process in sample.processes:
            if isinstance(process, dict):
                try:
                    process = ProcessUsage(**process)
                except (TypeError, ValueError) as exc:
                    raise AcceptanceFailure("invalid per-process GPU accounting") from exc
            if process.pid <= 0 or not process.name or process.used_mib < 0:
                raise AcceptanceFailure("invalid per-process GPU accounting")
    for previous, current in zip(ordered, ordered[1:]):
        gap = current.timestamp_ms - previous.timestamp_ms
        if gap <= 0:
            raise AcceptanceFailure("GPU sample monotonic clock is not increasing")
        if gap > max_gap_ms:
            raise AcceptanceFailure(f"GPU sampler gap exceeds {max_gap_ms} ms")
        if previous.wall_timestamp_ms is not None and current.wall_timestamp_ms is not None:
            wall_gap = current.wall_timestamp_ms - previous.wall_timestamp_ms
            if wall_gap <= 0 or abs(wall_gap - gap) > max_gap_ms:
                raise AcceptanceFailure("monotonic/wall clock reconciliation failed")
    return ordered


def validate_phase_markers(markers: Mapping[str, Mapping[str, int]], samples: Iterable[Sample], *, config: PhaseConfig | None = None) -> None:
    config = config or PhaseConfig()
    missing = [phase for phase in REQUIRED_PHASES if phase not in markers]
    if missing:
        raise AcceptanceFailure(f"missing phase markers: {','.join(missing)}")
    ordered = validate_samples(samples)
    first, last = ordered[0].timestamp_ms, ordered[-1].timestamp_ms
    previous_end = first
    for phase in REQUIRED_PHASES:
        marker = markers[phase]
        start, end = marker.get("start_ms"), marker.get("end_ms")
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
            raise AcceptanceFailure(f"invalid {phase} phase marker")
        if start < first or end <= start or end > last:
            raise AcceptanceFailure(f"{phase} phase marker is outside sample clock")
        if start < previous_end:
            raise AcceptanceFailure("phase markers overlap or are out of order")
        previous_end = end
    if markers["baseline"]["end_ms"] - markers["baseline"]["start_ms"] < config.baseline_seconds * 1000:
        raise AcceptanceFailure(f"baseline phase must cover {config.baseline_seconds} seconds")
    if markers["post"]["end_ms"] - markers["post"]["start_ms"] < config.post_seconds * 1000:
        raise AcceptanceFailure(f"post phase must cover {config.post_seconds} seconds")


def validate_overlap(markers: Mapping[str, Mapping[str, int]], minimum_ms: int = 5_000) -> None:
    for phase in ("active", "active_repeat"):
        marker = markers[phase]
        ds, de = marker.get("dots_start_ms", marker["start_ms"]), marker.get("dots_end_ms", marker["end_ms"])
        ws, we = marker.get("whisper_start_ms", marker["start_ms"]), marker.get("whisper_end_ms", marker["end_ms"])
        if not (marker["start_ms"] <= ds < de <= marker["end_ms"] and marker["start_ms"] <= ws < we <= marker["end_ms"]):
            raise AcceptanceFailure(f"{phase} workload interval is outside its phase")
        if min(de, we) - max(ds, ws) < minimum_ms:
            raise AcceptanceFailure(f"{phase} workload overlap is below {minimum_ms} ms")


def _samples_from_evidence(raw: Iterable[Any]) -> tuple[Sample, ...]:
    try:
        return tuple(Sample(**item) if isinstance(item, dict) else item for item in raw)
    except (TypeError, ValueError) as exc:
        raise AcceptanceFailure("malformed GPU observation") from exc


def validate_acceptance(evidence: Mapping[str, Any], *, config: PhaseConfig | None = None) -> dict[str, Any]:
    required = ("samples", "phase_markers", "health", "outputs", "cleanup", "backends")
    missing = [key for key in required if key not in evidence]
    if missing:
        raise AcceptanceFailure(f"missing evidence fields: {','.join(missing)}")
    samples = _samples_from_evidence(evidence["samples"])
    validate_samples(samples, nominal_interval_ms=(config or PhaseConfig()).sample_interval_ms)
    validate_phase_markers(evidence["phase_markers"], samples, config=config)
    validate_overlap(evidence["phase_markers"])
    health, outputs, cleanup, backends = evidence["health"], evidence["outputs"], evidence["cleanup"], evidence["backends"]
    for key in ("app", "dots", "worker_ready", "ollama_unloaded"):
        if health.get(key) is not True:
            raise AcceptanceFailure(f"health check failed: {key}")
    if health.get("unknown_gpu_processes") is True or health.get("restarts", 0) != 0:
        raise AcceptanceFailure("unknown GPU process ownership or unexpected container restart")
    if any(health.get(key) is True for key in ("queue_overflow", "cpu_offload", "oom", "readiness_loss", "model_eviction")):
        raise AcceptanceFailure("workload health check failed")
    for key in ("dots_first", "dots_second", "whisper_cold", "whisper_repeat"):
        if outputs.get(key) is not True:
            raise AcceptanceFailure(f"invalid or incomplete output: {key}")
    if cleanup.get("memory_drift_mib", 10**9) > 512 or cleanup.get("app_healthy") is not True:
        raise AcceptanceFailure("cleanup memory drift or health check failed")
    if backends.get("whisper") != "mock" or backends.get("diarize") != "mock":
        raise AcceptanceFailure("production backends are not mock")
    total = samples[0].total_mib
    if any(sample.total_mib != total for sample in samples):
        raise AcceptanceFailure("GPU total memory changed during measurement")
    peak = max(samples, key=lambda sample: sample.used_mib)
    minimum_free = min(sample.free_mib for sample in samples)
    threshold = max(2048, (total + 9) // 10)
    if minimum_free < threshold:
        raise AcceptanceFailure("VRAM headroom threshold failed")
    peak_processes = [p if isinstance(p, dict) else p.__dict__ for p in peak.processes]
    return sanitize({"verdict": "PASS", "total_mib": total, "peak_used_mib": peak.used_mib, "minimum_free_mib": minimum_free, "required_headroom_mib": threshold, "peak_phase": peak.phase, "peak_processes": peak_processes, "sample_count": len(samples)})


def mock_evidence(*, config: PhaseConfig | None = None) -> dict[str, Any]:
    config = config or PhaseConfig()
    durations = (10000, 10000, 10000, 10000, 10000, config.post_seconds * 1000)
    markers: dict[str, dict[str, int]] = {}
    cursor = 0
    for phase, duration in zip(REQUIRED_PHASES, durations):
        markers[phase] = {"start_ms": cursor, "end_ms": cursor + duration}
        cursor += duration
    for phase in ("active", "active_repeat"):
        marker = markers[phase]
        marker.update(dots_start_ms=marker["start_ms"] + 1000, dots_end_ms=marker["end_ms"] - 1000, whisper_start_ms=marker["start_ms"] + 2000, whisper_end_ms=marker["end_ms"] - 2000)
    samples = [{"timestamp_ms": t, "wall_timestamp_ms": 1_000_000 + t, "total_mib": 32768, "used_mib": 12000, "phase": next(p for p, m in markers.items() if m["start_ms"] <= t <= m["end_ms"]), "processes": [{"pid": 101, "name": "approved-worker", "used_mib": 8000}]} for t in range(0, cursor + 1, config.sample_interval_ms)]
    return {"samples": samples, "phase_markers": markers, "health": {"app": True, "dots": True, "worker_ready": True, "ollama_unloaded": True, "restarts": 0}, "outputs": {"dots_first": True, "dots_second": True, "whisper_cold": True, "whisper_repeat": True}, "cleanup": {"memory_drift_mib": 0, "app_healthy": True}, "backends": {"whisper": "mock", "diarize": "mock"}}


def discovery(run: Callable[[list[str]], str] | None = None) -> dict[str, Any]:
    """Read-only coarse discovery, only when explicitly requested.

    The result is a bounded allowlist: only opaque, non-sensitive fields are kept
    (GPU model name, aggregate memory numbers, service count/status, backend env
    values).  Raw command stdout is parsed into this shape and then sanitized; any
    residual private path, transcript fragment, runtime ID, or secret is redacted.
    Arbitrary command output is never echoed verbatim into evidence.
    """
    runner = run or (lambda command: subprocess.run(command, check=False, capture_output=True, text=True, timeout=10).stdout)
    try:
        gpu_raw = runner(["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"])
        compose_raw = runner(["docker", "compose", "ps", "--format", "json"])
        # Parse the GPU line into bounded numeric/opaque fields only.
        gpu_fields = [field.strip() for field in gpu_raw.split(",")] if gpu_raw else []
        gpu = {
            "model": gpu_fields[0] if gpu_fields else "unknown",
            "memory_total_mib": int(gpu_fields[1]) if len(gpu_fields) > 1 and gpu_fields[1].isdigit() else None,
            "memory_used_mib": int(gpu_fields[2]) if len(gpu_fields) > 2 and gpu_fields[2].isdigit() else None,
            "raw_length_redacted": len(gpu_raw or ""),
        }
        try:
            services = json.loads(compose_raw) if compose_raw else []
        except (ValueError, TypeError):
            services = []
        compose = {
            "service_count": len(services) if isinstance(services, list) else 0,
            "states": sorted({str(item.get("State", "unknown")) for item in services}) if isinstance(services, list) else [],
        }
        return sanitize({
            "mode": "read_only_discovery",
            "gpu": gpu,
            "compose": compose,
            "production_backends": {"whisper": os.getenv("WHISPER_BACKEND", "unset"), "diarize": os.getenv("DIARIZE_BACKEND", "unset")},
        })
    except Exception as exc:
        raise AcceptanceFailure("read-only discovery failed") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discover", action="store_true", help="explicit read-only discovery")
    parser.add_argument("--mock", action="store_true", help="run deterministic offline acceptance (default)")
    parser.add_argument("--evidence", type=Path, help="validate existing sanitized evidence JSON")
    parser.add_argument("--execute", action="store_true", help="reserved; live execution is never implicit")
    args = parser.parse_args(argv)
    try:
        if args.execute:
            if os.getenv("PETER_AI_GPU_ACCEPTANCE") != "1":
                raise AcceptanceFailure("live acceptance requires explicit authorization")
            raise AcceptanceFailure("live execution is disabled in the sanitized harness")
        if args.discover:
            result = discovery()
        elif args.evidence:
            result = validate_acceptance(json.loads(args.evidence.read_text(encoding="utf-8")))
        else:
            result = AcceptanceHarness().run()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AcceptanceFailure, OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"verdict": "FAIL", "error": sanitize(str(exc))}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
