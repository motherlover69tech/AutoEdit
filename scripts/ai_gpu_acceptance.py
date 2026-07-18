#!/usr/bin/env python3
"""Sanitized, offline-first AI-GPU-1 acceptance harness.

This harness is the Programmer-owned implementation of the reviewed operational
design described in ``docs/plans/ai-gpu-1-acceptance-runbook.md`` and the
canonical machine contract ``docs/plans/ai-gpu-1-redacted-evidence.schema.json``
(version ``1.0.0``).

It produces and validates *canonical* redacted evidence: the instance it builds
conforms to the canonical schema, and every ``x-autoedit-semantic-rules`` rule is
executed by the harness, not merely documented.

Modes (explicit; no mode is implied; no args prints usage and exits nonzero):

* ``plan``     -- local schema/config parsing only; no external command.
* ``discover`` -- allowlisted read-only inspection only; bounded, redacted output.
* ``validate`` -- validate an existing redacted evidence instance; no live action.
* ``mock``     -- deterministic injected adapters and fake clocks; no network/exec.
* ``execute``  -- reserved for an authorized live workflow; never implicit here.

Live execution is deliberately not implemented in this safe harness. ``execute``
is accepted only with the same-host discovery bundle, the scoped current
authorization record, the immutable candidate identifiers, and the private
fixture binding; without them it fails with the ``unauthorized`` exit class and
does not perform any live action.

No command, HTTP request, container operation, or GPU query is performed by
``plan``, ``discover`` (a thin bounded allowlist), ``validate``, or ``mock``.
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
from typing import Any

import jsonschema

# ---------------------------------------------------------------------------
# Paths / canonical contract
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
HARNESS_SCHEMA_PATH = SCRIPT_DIR / "ai_gpu_acceptance_evidence.schema.json"
CANONICAL_SCHEMA_PATH = (
    SCRIPT_DIR.parent / "docs" / "plans" / "ai-gpu-1-redacted-evidence.schema.json"
)

# ---------------------------------------------------------------------------
# Exit classes (runbook section 2)
# ---------------------------------------------------------------------------
EXIT_SUCCESS = 0
EXIT_VALIDATION_FAILURE = 2
EXIT_UNAVAILABLE = 3
EXIT_UNAUTHORIZED = 4
EXIT_ADAPTER_ERROR = 5
EXIT_REDACTION_FAILURE = 6
EXIT_CLEANUP_ROLLBACK_FAILURE = 7

REQUIRED_PHASES = (
    "baseline",
    "dots_resident",
    "whisper_cold",
    "co_resident_idle",
    "active_overlap_1",
    "active_overlap_2",
    "post_workload",
    "cleanup_verify",
)
NOMINAL_INTERVAL_MS = 250
MAX_GAP_MS = 500
MAX_RECONCILIATION_ERROR_MS = 500
MINIMUM_OVERLAP_MS = 5_000
BASELINE_MINIMUM_MS = 10_000
DOTS_RESIDENT_MINIMUM_MS = 10_000
POST_WORKLOAD_MINIMUM_MS = 30_000
CLEANUP_DRIFT_LIMIT_MIB = 512

# ---------------------------------------------------------------------------
# Redaction (SEC-AIGPU1-002).  Drop secret-bearing keys entirely; replace
# credentialed URLs; never retain raw output, private paths, transcript text,
# names, or runtime IDs.
# ---------------------------------------------------------------------------
SECRET_KEY_RE = re.compile(
    r"(?i)(token|password|secret|cookie|credential|authorization|api[_-]?key|"
    r"bearer|private[_-]?key|passwd)"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(token|password|secret|cookie|authorization|api[_-]?key|credential)"
    r"\s*[=:]\s*\S+"
)
URL_SECRET_RE = re.compile(r"(?i)(https?://)([^/@\s]+):([^/@\s]+)@")
# Bounded allowlist patterns for discovery output.  Anything that looks like a
# private path, transcript fragment, person name fragment, or runtime id is
# replaced with an opaque redaction token (BUG-AIGPU1-002).
PRIVATE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._/-])(/[^\s,;'\"]+|[A-Za-z]:\\[^\s,;'\"]+)"
)
TRANSCRIPT_RE = re.compile(r"(?i)\b(transcript|prompt|word|subtitle)[=:]?\s*\S+")
RUNTIME_ID_RE = re.compile(
    r"(?i)\b(?:runtime-id|run-id|container-id|proc-id|container_id|pid)[-_ ]?"
    r"[=:]?[ -]?[A-Za-z0-9._-]{2,}"
)
NAME_RE = re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b")  # "Alice Smith" style names

# Discovery becomes durable evidence. Printable/free-form host labels are not
# safe; retain only operational allowlists needed by the redacted contract.
SAFE_GPU_MODELS = frozenset({
    "Tesla V100", "Tesla-V100", "Tesla-V100-SXM2-32GB",
    "Tesla V100-SXM2-32GB",
})
SAFE_SERVICE_STATES = frozenset({
    "created", "dead", "exited", "paused", "restarting", "running",
})
SAFE_BACKENDS = frozenset({"mock", "whisperx", "real", "unset"})


class AcceptanceFailure(Exception):
    """A visible, fail-closed acceptance error carrying an exit class."""

    def __init__(self, message: str, exit_class: int = EXIT_VALIDATION_FAILURE) -> None:
        super().__init__(message)
        self.message = message
        self.exit_class = exit_class


def redact_scalar(value: str) -> str:
    redacted = URL_SECRET_RE.sub(r"\1[REDACTED]@", value)
    redacted = SECRET_VALUE_RE.sub("[REDACTED]", redacted)
    redacted = RUNTIME_ID_RE.sub("[REDACTED-ID]", redacted)
    redacted = TRANSCRIPT_RE.sub("[REDACTED-CONTENT]", redacted)
    redacted = PRIVATE_PATH_RE.sub("[REDACTED-PATH]", redacted)
    redacted = NAME_RE.sub("[REDACTED-NAME]", redacted)
    return redacted


def sanitize(value: Any) -> Any:
    """Recursively drop secret-bearing keys and redact private scalars."""
    if isinstance(value, dict):
        return {
            str(k): sanitize(v)
            for k, v in value.items()
            if not SECRET_KEY_RE.search(str(k))
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_scalar(value)
    return value


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _utc_rfc3339(ns: int) -> str:
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ns % 1_000_000_000:09d}Z"


def _sha256_of(text: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Adapters (side-effect boundary)
# ---------------------------------------------------------------------------
class AcceptanceAdapter:
    """Injectable adapter; production adapters must be supplied explicitly."""

    def run_read_only(self, command: list[str], timeout_s: int = 10) -> str:
        raise AcceptanceFailure(
            "no adapter configured for live read-only discovery",
            exit_class=EXIT_UNAVAILABLE,
        )

    def submit_workload(self, kind: str) -> dict[str, Any]:
        raise AcceptanceFailure(
            "live workload submission is not implemented in the sanitized harness",
            exit_class=EXIT_UNAUTHORIZED,
        )


@dataclass
class MockAdapter(AcceptanceAdapter):
    """Deterministic offline adapter used by ``mock`` mode and tests."""

    checks: dict[str, bool] = field(
        default_factory=lambda: {name: True for name in (
            "app_healthy", "dots_healthy", "worker_ready", "ollama_unloaded",
            "outputs_valid", "cleanup_drift_ok", "app_healthy_after_cleanup",
            "mock_backends_restored",
        )}
    )

    def run_read_only(self, command: list[str], timeout_s: int = 10) -> str:
        # The allowlisted, non-mutating discovery commands.  Output is bounded
        # and then parsed into an opaque, redacted shape by discover().
        if command[:1] == ["nvidia-smi"]:
            return "Tesla-V100-SXM2-32GB,32768,12000"
        if command[:2] == ["docker", "compose"] and "ps" in command:
            return json.dumps([{"Name": "autoedit", "State": "running"}])
        if command[:1] == ["docker"] and "inspect" in command:
            return json.dumps([{"State": {"Health": {"Status": "healthy"}}}])
        raise AcceptanceFailure(
            f"non-allowlisted discovery command: {command}",
            exit_class=EXIT_ADAPTER_ERROR,
        )


class LocalReadOnlyAdapter(AcceptanceAdapter):
    """Read-only host discovery adapter used by the CLI ``--discover``.

    Shells out only to the allowlisted, non-mutating commands. Any command
    outside the allowlist, a nonzero exit, a timeout, or a missing tool is
    reported as ``unavailable`` (never silently faked, never mutated).
    """

    def run_read_only(self, command: list[str], timeout_s: int = 10) -> str:
        cmd = tuple(command)
        if cmd not in ALLOWED_DISCOVERY:
            raise AcceptanceFailure(
                f"non-allowlisted discovery command: {cmd}",
                exit_class=EXIT_ADAPTER_ERROR,
            )
        try:
            proc = subprocess.run(
                list(command), check=False, capture_output=True, text=True,
                timeout=timeout_s,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AcceptanceFailure(
                f"read-only discovery command unavailable: {cmd[0]}",
                exit_class=EXIT_UNAVAILABLE,
            ) from exc
        if proc.returncode != 0:
            raise AcceptanceFailure(
                f"read-only discovery command failed: {cmd[0]} rc={proc.returncode}",
                exit_class=EXIT_UNAVAILABLE,
            )
        return proc.stdout


# ---------------------------------------------------------------------------
# Required canonical evidence builder (offline / mock)
# ---------------------------------------------------------------------------
def _mock_run_id() -> str:
    return "run-" + _sha256_of("mock-run").replace("sha256:", "")[:16]


def build_mock_evidence() -> dict[str, Any]:
    """A fully canonical, redacted evidence instance for offline modes.

    It is accepted only for plan/validate/mock purposes: ``run.mode`` is
    ``mock`` and the overall/run flags record ``acceptance_eligible=false`` and
    ``acceptance_pass=false`` (VAL-MODE-001).  It still demonstrates every
    required field, exact candidate binding (BUG-AIGPU1-001), and the canonical
    semantic rules so the harness can exercise and prove them offline.
    """
    run_id = _mock_run_id()
    total_mib = 32768
    used_idle = 12000
    t0 = 1_700_000_000_000_000_000  # fixed fake monotonic ns anchor

    def phase_windows():
        # 8 phases, 10s/10s/10s/5s/10s/10s/30s/10s -> monotonic windows
        durations = [10_000, 10_000, 10_000, 5_000, 10_000, 10_000, 30_000, 10_000]
        windows = {}
        cursor = 0
        for phase, dur in zip(REQUIRED_PHASES, durations):
            windows[phase] = (cursor, cursor + dur)
            cursor += dur
        return windows, cursor

    windows, total_ms = phase_windows()

    # --- phase markers (monotonic + wall, 0..7) ---
    phase_markers = {}
    for seq, phase in enumerate(REQUIRED_PHASES):
        start, end = windows[phase]
        phase_markers[phase] = {
            "status": "pass",
            "sequence": seq,
            "start_monotonic_ns": t0 + start * 1_000_000,
            "end_monotonic_ns": t0 + end * 1_000_000,
            "start_wall_utc": _utc_rfc3339(t0 + start * 1_000_000),
            "end_wall_utc": _utc_rfc3339(t0 + end * 1_000_000),
            "duration_ms": end - start,
            "start_event": f"{phase.upper()}_START",
            "end_event": f"{phase.upper()}_END",
        }

    # --- samples: one device total, <=250ms nominal, <=500ms gaps ---
    samples = []
    processes = [
        {"pid": 101, "name": "approved-worker", "role": "whisper_worker",
         "used_mib": 8000, "attribution_status": "approved"},
        {"pid": 102, "name": "dots", "role": "dots",
         "used_mib": 3000, "attribution_status": "approved"},
    ]
    services = [
        {"service_ref": "svc-app", "health": "healthy", "readiness": "ready",
         "restart_count": 0},
        {"service_ref": "svc-worker", "health": "healthy", "readiness": "ready",
         "restart_count": 0},
        {"service_ref": "svc-dots", "health": "healthy", "readiness": "ready",
         "restart_count": 0},
    ]
    # overlap windows (active phases): dots + whisper each >=5000ms overlap
    overlap = {
        "active_overlap_1": (windows["active_overlap_1"][0] + 1000,
                             windows["active_overlap_1"][1] - 1000),
        "active_overlap_2": (windows["active_overlap_2"][0] + 1000,
                             windows["active_overlap_2"][1] - 1000),
    }
    cursor = 0
    global_t = 0
    for phase in REQUIRED_PHASES:
        start, end = windows[phase]
        # Continuous clock across phases: begin each phase one nominal tick
        # after the previous boundary so no sample timestamp is duplicated.
        phase_start = global_t
        phase_end = global_t + (end - start)
        global_t = phase_end + NOMINAL_INTERVAL_MS
        for t in range(phase_start, phase_end + 1, NOMINAL_INTERVAL_MS):
            cursor += 1
            wall = t0 + t * 1_000_000
            tags = ["idle"]
            if phase == "dots_resident":
                tags = ["dots_load", "dots_resident"]
            elif phase == "whisper_cold":
                tags = ["whisper_model_load", "whisper_readiness", "whisper_asr"]
            elif phase in overlap:
                tags = ["dots_inference", "whisper_asr", "whisper_alignment",
                        "whisper_diarization"]
            elif phase == "cleanup_verify":
                tags = ["cleanup"]
            samples.append({
                "sequence": cursor,
                "scheduled_monotonic_ns": wall,
                "observed_monotonic_ns": wall,
                "wall_utc": _utc_rfc3339(wall),
                "phase": phase,
                "activity_tags": tags,
                "total_mib": total_mib,
                "used_mib": used_idle,
                "free_mib": total_mib - used_idle,
                "processes": processes,
                "services": services,
            })

    peak = max(samples, key=lambda s: s["used_mib"])
    minimum_free = min(s["free_mib"] for s in samples)
    required_headroom = max(2048, (total_mib + 9) // 10)
    contributing_pids = sorted({p["pid"] for p in processes})

    measurement = {
        "status": "pass",
        "configuration": {
            "nominal_interval_ms": NOMINAL_INTERVAL_MS,
            "maximum_gap_ms": MAX_GAP_MS,
            "baseline_minimum_ms": BASELINE_MINIMUM_MS,
            "dots_resident_minimum_ms": DOTS_RESIDENT_MINIMUM_MS,
            "post_workload_minimum_ms": POST_WORKLOAD_MINIMUM_MS,
            "active_overlap_minimum_ms": MINIMUM_OVERLAP_MS,
            "cleanup_drift_limit_mib": CLEANUP_DRIFT_LIMIT_MIB,
        },
        "clocks": {
            "status": "pass",
            "monotonic_clock": "monotonic_ns",
            "wall_clock": "utc_rfc3339",
            "maximum_reconciliation_error_ms": MAX_RECONCILIATION_ERROR_MS,
            "observed_reconciliation_error_ms": 0,
        },
        "phases": phase_markers,
        "interval_statistics": {
            "sample_count": len(samples),
            "minimum_ms": float(NOMINAL_INTERVAL_MS),
            "median_ms": float(NOMINAL_INTERVAL_MS),
            "p95_ms": float(NOMINAL_INTERVAL_MS),
            "maximum_ms": float(NOMINAL_INTERVAL_MS),
            "missed_tick_count": 0,
            "continuity_status": "pass",
        },
        "samples": samples,
        "vram_summary": {
            "status": "pass",
            "total_mib": total_mib,
            "peak_used_mib": peak["used_mib"],
            "minimum_free_mib": minimum_free,
            "required_headroom_mib": required_headroom,
            "peak_phase": peak["phase"],
            "peak_sample_sequence": peak["sequence"],
            "contributing_pids": contributing_pids,
            "unknown_process_count": 0,
        },
    }

    def workload_interval(ref, kind, phase, start, end):
        return {
            "workload_ref": ref,
            "kind": kind,
            "phase": phase,
            "status": "pass",
            "start_monotonic_ns": t0 + start * 1_000_000,
            "end_monotonic_ns": t0 + end * 1_000_000,
            "start_wall_utc": _utc_rfc3339(t0 + start * 1_000_000),
            "end_wall_utc": _utc_rfc3339(t0 + end * 1_000_000),
        }

    def whisper_output(ref, phase):
        return {
            "output_ref": ref,
            "phase": phase,
            "status": "pass",
            "job_done": True,
            "input_hash_match": True,
            "nonempty_aligned_words": True,
            "ordered_bounded_integer_times": True,
            "two_speaker_turns": True,
            "raw_payload_present": False,
        }

    def dots_output(ref, phase):
        return {
            "output_ref": ref,
            "phase": phase,
            "status": "pass",
            "nonempty_bytes": 1024,
            "playable_probe": True,
            "duration_ms": 9000,
            "post_processing_reported_separately": True,
            "raw_audio_present": False,
        }

    def overlap_obj(ref_whisper, ref_dots, phase):
        ds, de = overlap[phase]
        return {
            "status": "pass",
            "phase": phase,
            "whisper_workload_ref": ref_whisper,
            "dots_workload_ref": ref_dots,
            "overlap_ms": (de - ds),
            "minimum_ms": MINIMUM_OVERLAP_MS,
        }

    workloads = {
        "status": "pass",
        "intervals": [
            workload_interval("wl-whisper-cold", "whisper_readiness", "whisper_cold",
                              windows["whisper_cold"][0], windows["whisper_cold"][1]),
            workload_interval("wl-dots-resident", "dots_inference", "whisper_cold",
                              windows["whisper_cold"][0] + 1000, windows["whisper_cold"][1] - 1000),
            workload_interval("wl-whisper-1", "whisper_analysis", "active_overlap_1",
                              windows["active_overlap_1"][0], windows["active_overlap_1"][1]),
            workload_interval("wl-whisper-2", "whisper_analysis", "active_overlap_2",
                              windows["active_overlap_2"][0], windows["active_overlap_2"][1]),
            workload_interval("wl-dots-1", "dots_inference", "active_overlap_1",
                              overlap["active_overlap_1"][0], overlap["active_overlap_1"][1]),
            workload_interval("wl-dots-2", "dots_inference", "active_overlap_2",
                              overlap["active_overlap_2"][0], overlap["active_overlap_2"][1]),
        ],
        "whisper_outputs": [
            whisper_output("out-whisper-cold", "whisper_cold"),
            whisper_output("out-whisper-1", "active_overlap_1"),
            whisper_output("out-whisper-2", "active_overlap_2"),
        ],
        "dots_outputs": [
            dots_output("out-dots-1", "active_overlap_1"),
            dots_output("out-dots-2", "active_overlap_2"),
        ],
        "overlaps": [
            overlap_obj("wl-whisper-1", "wl-dots-1", "active_overlap_1"),
            overlap_obj("wl-whisper-2", "wl-dots-2", "active_overlap_2"),
        ],
    }

    services_block = {
        "status": "pass",
        "observations": [
            {"service_ref": "svc-app", "role": "autoedit_app", "phase": "baseline",
             "monotonic_ns": t0, "wall_utc": _utc_rfc3339(t0),
             "health": "healthy", "readiness": "ready", "restart_count": 0,
             "loaded_model_count": 0},
            {"service_ref": "svc-dots", "role": "dots", "phase": "dots_resident",
             "monotonic_ns": t0, "wall_utc": _utc_rfc3339(t0),
             "health": "healthy", "readiness": "ready", "restart_count": 0,
             "loaded_model_count": 0},
            {"service_ref": "svc-ollama", "role": "ollama", "phase": "cleanup_verify",
             "monotonic_ns": t0, "wall_utc": _utc_rfc3339(t0),
             "health": "not_applicable", "readiness": "not_applicable",
             "restart_count": 0, "loaded_model_count": 0},
        ],
        "restart_delta_zero": True,
        "ollama_unloaded_all_phases": True,
        "incidents": {
            "oom": False, "cpu_offload": False, "model_eviction": False,
            "readiness_loss": False, "app_health_loss": False,
            "dots_health_loss": False, "queue_overflow": False,
            "unexpected_restart": False,
        },
    }

    compose_render = "app:\n  image: autoedit:mock\nworker:\n  image: whisper-worker:mock\n"
    cleanup = {
        "status": "pass",
        "actions": [
            {"resource_ref": "res-temp-worker", "action": "stop_temporary_worker",
             "authorized": True, "status": "pass"},
            {"resource_ref": "res-acceptance-model", "action": "unload_acceptance_model",
             "authorized": True, "status": "pass"},
        ],
        "unapproved_resource_mutation_attempted": False,
        "baseline_idle_median_used_mib": used_idle,
        "post_cleanup_idle_median_used_mib": used_idle,
        "raw_drift_mib": 0,
        "allowed_drift_mib": CLEANUP_DRIFT_LIMIT_MIB,
        "resident_exception": {
            "applied": False, "preauthorized": False,
            "service_ref": None, "explained_mib": 0,
        },
        "adjusted_drift_mib": 0,
        "app_healthy_after_cleanup": True,
        "production_backends_after_cleanup": {"whisper": "mock", "diarize": "mock"},
        "prior_artifacts_and_cuts_preserved": True,
        "rollback": {
            "status": "pass", "triggered": False,
            "worker_stopped_if_authorized": True,
            "mock_left_or_restored": True,
            "retry_changed_production_defaults": False,
        },
    }

    commands = [
        {
            "operation_id": "op-discover-gpu", "phase": "discovery",
            "read_only": True, "authorization_required": False,
            "authorization_ref": None,
            "argv_redacted": ["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                              "--format=csv,noheader,nounits"],
            "started_at_utc": _utc_rfc3339(t0),
            "ended_at_utc": _utc_rfc3339(t0 + 100_000_000),
            "exit_code": 0, "timed_out": False,
            "stdout_retained": False, "stderr_retained": False,
            "result_digest": _sha256_of("mock"), "redaction_status": "pass",
        }
    ]

    test_results = [
        {"test_ref": f"t-{scenario}", "scenario_id": scenario, "status": "pass",
         "command_ref": "op-discover-gpu", "exit_code": 0,
         "external_access_attempted": False}
        for scenario in (
            "positive_schema_valid_redacted", "nominal_interval_too_slow",
            "sampler_gap", "phase_missing", "baseline_too_short",
            "resident_too_short", "post_too_short", "process_accounting_absent",
            "clock_irreconcilable", "health_failure", "restart_detected",
            "readiness_failure", "app_failure", "dots_failure", "ollama_loaded",
            "output_invalid", "overlap_too_short", "cleanup_drift",
            "mock_backend_recheck_failure", "unknown_gpu_process",
            "vram_headroom_failure", "authorization_missing",
            "non_read_only_discovery_rejected", "redaction_secret_input",
            "redaction_secret_output", "wrong_input_hash", "worker_unavailable",
            "persistence_failure", "stale_mapping", "unresolved_identity",
            "missing_wide_camera",
        )
    ]

    requirement_results = {}
    for req in (
        "OPS-AIGPU1-001", "OPS-AIGPU1-002", "OPS-AIGPU1-003", "OPS-AIGPU1-004",
        "OPS-AIGPU1-005", "OPS-AIGPU1-006", "OPS-AIGPU1-007", "OPS-AIGPU1-008",
        "SEC-AIGPU1-002", "SEC-AIGPU1-003", "TEST-AIGPU1-005",
        "TEST-AIGPU1-007", "TEST-AIGPU1-008",
    ):
        requirement_results[req] = {
            "status": "pass",
            "validation_rule_ids": ["VAL-TEST-001"],
            "evidence_refs": ["#/tests/results"],
            "failure_codes": [],
        }

    # Exact candidate binding (BUG-AIGPU1-001): immutable identifiers, not
    # placeholders. These are mock/opaque values; only a live run with the real
    # Peter-supplied binding may set acceptance_eligible=true.
    candidate = {
        "status": "pass",
        "source_commit": "24b537a3666115aaae2b13100738adf5531767ec",
        "worker_image_digest": _sha256_of("whisper-worker:mock"),
        "compose_redacted_render_digest": _sha256_of(compose_render),
        "worker_runtime": {
            "python": "3.13.5", "cuda": "12.4", "whisperx": "3.1.0",
            "torch": "2.4.0", "pyannote": "3.1.0",
        },
        "whisper_configuration": {
            "model": "large-v3", "compute_type": "float16", "language": "en",
            "alignment": True, "batch_size": 4, "diarization": True,
            "min_speakers": 2, "max_speakers": 2, "queue_concurrency": 1,
        },
        "dots_configuration": {
            "quality_config_ref": "dots-quality-stable",
            "input_character_count": 600, "steps": 12, "guidance": 1.3,
            "gpu_measurement_excludes_post_processing": True,
        },
    }

    project_context = {
        "status": "pass",
        "project_ref": "proj-autoedit",
        "fixture_ref": "fix-consent-cleared",
        "acceptance_run_ref": run_id,
        "fps_num": 30, "fps_den": 1,
        "automatic_sync_offsets": [
            {"channel_ref": "ch-a", "sync_offset_ms": 0, "applied_exactly_once": True},
            {"channel_ref": "ch-b", "sync_offset_ms": 0, "applied_exactly_once": True},
        ],
        "input_hash_match": True,
        "raw_media_hash_present": False,
    }

    return {
        "schema_version": "1.0.0",
        "evidence_class": "redacted_audit",
        "run": {
            "run_id": run_id,
            "mode": "mock",
            "status": "pass",
            "started_at_utc": _utc_rfc3339(t0),
            "ended_at_utc": _utc_rfc3339(t0 + total_ms * 1_000_000),
            "acceptance_eligible": False,
            "preparation_or_mock_is_authorization": False,
            "exit": {"code": 0, "class": "success"},
        },
        "authorization": {
            "status": "unauthorized",
            "explicit_peter_authorization": False,
            "decision_ref": None,
            "authorized_window_start_utc": None,
            "authorized_window_end_utc": None,
            "scope": {
                "target_host_ref": None, "fixture_ref": None,
                "start_approved_worker": False, "load_or_exercise_dots": False,
                "unload_ollama": False, "submit_whisper_jobs": False,
                "cleanup_resource_refs": [],
            },
            "preparation_acknowledged_as_non_authorizing": True,
        },
        "redaction": {
            "status": "pass",
            "policy_version": "AI-GPU-1-REDACTION-1",
            "raw_sensitive_payloads_present": False,
            "prohibited_categories": [
                "credentials", "tokens", "cookies", "authorization_headers",
                "secret_values", "raw_media", "raw_audio", "transcript_text",
                "dots_input_text", "human_names", "exact_private_paths",
                "private_media_hashes", "screenshots_or_recordings_with_media",
                "raw_http_payloads", "raw_environment_dumps", "container_runtime_ids",
            ],
            "transformations": [
                {"category": "cat-secret-keys", "action": "drop",
                 "replacement": "none"},
                {"category": "cat-secret-values", "action": "replace",
                 "replacement": "REDACTED"},
                {"category": "cat-private-paths", "action": "replace",
                 "replacement": "run_scoped_alias"},
                {"category": "cat-runtime-ids", "action": "replace",
                 "replacement": "run_scoped_alias"},
            ],
            "secret_source": {
                "status": "pass", "source_ref": "src-approved",
                "approved_source": True, "values_persisted": False,
                "values_in_argv": False, "values_in_public_errors": False,
            },
            "scan": {
                "status": "pass", "scanner_version": "scan-1.0.0",
                "files_scanned": 1, "findings": 0,
            },
        },
        "candidate": candidate,
        "project_context": project_context,
        "discovery": {
            "status": "unavailable",
            "read_only": True,
            "completed_before_live_activity": False,
            "implicit_start_or_mutation_attempted": False,
            "observations": {
                "gpu_cpu_ram": {"status": "unavailable",
                                "source_operation_id": "op-discover-gpu",
                                "evidence_refs": ["#/discovery/gpu_devices"],
                                "failure_code": None},
                "docker_compose_topology": {"status": "unavailable",
                                            "source_operation_id": "op-discover-compose",
                                            "evidence_refs": ["#/discovery/docker_services"],
                                            "failure_code": None},
                "network_ports_reverse_proxy": {"status": "unavailable",
                                                "source_operation_id": "op-discover-net",
                                                "evidence_refs": ["#/discovery/network_bindings"],
                                                "failure_code": None},
                "volumes_appdata_cache_permissions": {"status": "unavailable",
                                                      "source_operation_id": "op-discover-vol",
                                                      "evidence_refs": ["#/discovery/volumes"],
                                                      "failure_code": None},
                "health_restart_readiness": {"status": "unavailable",
                                             "source_operation_id": "op-discover-health",
                                             "evidence_refs": ["#/services"],
                                             "failure_code": None},
                "dots_state": {"status": "unavailable",
                               "source_operation_id": "op-discover-dots",
                               "evidence_refs": ["#/services"],
                               "failure_code": None},
                "ollama_state": {"status": "unavailable",
                                 "source_operation_id": "op-discover-ollama",
                                 "evidence_refs": ["#/services"],
                                 "failure_code": None},
                "production_backends": {"status": "unavailable",
                                        "source_operation_id": "op-discover-backends",
                                        "evidence_refs": ["#/compose/app_backends"],
                                        "failure_code": None},
                "persistent_data_backup_rollback": {"status": "unavailable",
                                                    "source_operation_id": "op-discover-backup",
                                                    "evidence_refs": ["#/cleanup_and_rollback/rollback"],
                                                    "failure_code": None},
            },
            "gpu_devices": [],
            "host_resources": {"logical_cpu_count": None, "ram_total_mib": None,
                               "ram_available_mib": None},
            "docker_services": [],
            "network_bindings": [],
            "volumes": [],
            "effective_backends": {"whisper": "mock", "diarize": "mock"},
        },
        "compose": {
            "status": "pass",
            "render_only": True,
            "container_start_attempted": False,
            "redacted_render_digest": _sha256_of(compose_render),
            "app_host_network": True,
            "worker_loopback_only": True,
            "worker_reachable_from_lan_or_npm": False,
            "media_mount_read_only": True,
            "media_path_confined": True,
            "model_cache_persistent": True,
            "readiness_healthcheck_present": True,
            "queue_concurrency": 1,
            "app_backends": {"whisper": "mock", "diarize": "mock"},
        },
        "measurement": measurement,
        "services": services_block,
        "workloads": workloads,
        "cleanup_and_rollback": cleanup,
        "commands": commands,
        "tests": {
            "status": "pass",
            "exact_candidate": True,
            "network_isolated": True,
            "results": test_results,
        },
        "requirement_results": requirement_results,
        "overall": {
            "status": "pass",
            "acceptance_pass": False,
            "failed_requirements": [],
            "residual_risk_codes": ["RISK-SAMPLE-LOSS", "RISK-ATTRIBUTION"],
            "summary_digest": _sha256_of(json.dumps({"mock": True}, sort_keys=True)),
        },
    }


# ---------------------------------------------------------------------------
# Validation: canonical schema + semantic rules
# ---------------------------------------------------------------------------
def load_canonical_schema() -> dict[str, Any]:
    path = CANONICAL_SCHEMA_PATH
    if not path.exists():
        raise AcceptanceFailure(
            f"canonical schema not found at {path}", exit_class=EXIT_ADAPTER_ERROR
        )
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schema(evidence: dict[str, Any]) -> None:
    schema = load_canonical_schema()
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(evidence), key=lambda e: e.path)
    except jsonschema.SchemaError as exc:
        raise AcceptanceFailure(
            f"canonical schema itself is invalid: {exc.message}",
            exit_class=EXIT_ADAPTER_ERROR,
        ) from exc
    if errors:
        first = errors[0]
        loc = "/".join(str(p) for p in first.path) or "<root>"
        raise AcceptanceFailure(
            f"schema validation failed at {loc}: {first.message}",
            exit_class=EXIT_VALIDATION_FAILURE,
        )


def validate_semantic_rules(evidence: dict[str, Any]) -> None:
    """Execute the x-autoedit-semantic-rules against the evidence instance."""
    # VAL-SAMPLE-001 / VAL-PHASE-001 / VAL-PROCESS-001 / VAL-CLOCK-001
    meas = evidence.get("measurement", {})
    cfg = meas.get("configuration", {})
    if not (1 <= cfg.get("nominal_interval_ms", 0) <= 250):
        raise AcceptanceFailure("nominal interval not in 1..250 ms", EXIT_VALIDATION_FAILURE)
    samples = meas.get("samples", [])
    if len(samples) < 2:
        raise AcceptanceFailure("fewer than two GPU samples", EXIT_VALIDATION_FAILURE)
    total = samples[0].get("total_mib")
    prev_seq = -1
    prev_obs = -1
    prev_wall = None
    for i, s in enumerate(samples):
        if s.get("total_mib") != total:
            raise AcceptanceFailure("GPU total memory changed during measurement",
                                    EXIT_VALIDATION_FAILURE)
        if not (s.get("total_mib") == s.get("used_mib") + s.get("free_mib")):
            raise AcceptanceFailure("sample does not reconcile total=used+free",
                                    EXIT_VALIDATION_FAILURE)
        if s.get("sequence", 0) <= prev_seq:
            raise AcceptanceFailure("sample sequence not strictly increasing",
                                    EXIT_VALIDATION_FAILURE)
        prev_seq = s.get("sequence", 0)
        obs = s.get("observed_monotonic_ns", 0)
        if obs <= prev_obs:
            raise AcceptanceFailure("sample monotonic clock not increasing",
                                    EXIT_VALIDATION_FAILURE)
        prev_obs = obs
        if i > 0:
            gap_ns = obs - samples[i - 1].get("observed_monotonic_ns", 0)
            if gap_ns > MAX_GAP_MS * 1_000_000:
                raise AcceptanceFailure(f"sampler gap exceeds {MAX_GAP_MS} ms",
                                        EXIT_VALIDATION_FAILURE)
        wall = s.get("wall_utc")
        if prev_wall is not None and wall is not None:
            err = abs(_wall_to_ns(wall) - obs) - abs(_wall_to_ns(prev_wall) - prev_obs)
            if abs(err) > MAX_RECONCILIATION_ERROR_MS * 1_000_000:
                raise AcceptanceFailure("monotonic/wall clock reconciliation failed",
                                        EXIT_VALIDATION_FAILURE)
        prev_wall = wall
        for p in s.get("processes", []):
            if p.get("pid", 0) <= 0 or not p.get("name") or p.get("used_mib", -1) < 0:
                raise AcceptanceFailure("invalid per-process GPU accounting",
                                        EXIT_VALIDATION_FAILURE)
            if p.get("attribution_status") != "approved":
                raise AcceptanceFailure("unknown/unapproved GPU process owner",
                                        EXIT_VALIDATION_FAILURE)

    # VAL-PHASE-001: 8 phases exactly once, order 0..7, coverage
    phases = meas.get("phases", {})
    for seq, phase in enumerate(REQUIRED_PHASES):
        if phase not in phases:
            raise AcceptanceFailure(f"missing phase marker: {phase}",
                                    EXIT_VALIDATION_FAILURE)
        if phases[phase].get("sequence") != seq:
            raise AcceptanceFailure(f"phase {phase} out of sequence order",
                                    EXIT_VALIDATION_FAILURE)
    if (phases["baseline"]["duration_ms"]) < BASELINE_MINIMUM_MS:
        raise AcceptanceFailure("baseline phase below 10 s", EXIT_VALIDATION_FAILURE)
    if (phases["dots_resident"]["duration_ms"]) < DOTS_RESIDENT_MINIMUM_MS:
        raise AcceptanceFailure("dots_resident phase below 10 s", EXIT_VALIDATION_FAILURE)
    if (phases["post_workload"]["duration_ms"]) < POST_WORKLOAD_MINIMUM_MS:
        raise AcceptanceFailure("post_workload phase below 30 s", EXIT_VALIDATION_FAILURE)

    # VAL-VRAM-001
    vram = meas.get("vram_summary", {})
    if vram.get("minimum_free_mib", 0) < vram.get("required_headroom_mib", 0):
        raise AcceptanceFailure("VRAM headroom threshold failed", EXIT_VALIDATION_FAILURE)
    if vram.get("unknown_process_count", 0) != 0:
        raise AcceptanceFailure("unknown GPU process in peak", EXIT_VALIDATION_FAILURE)

    # VAL-HEALTH-001
    svc = evidence.get("services", {})
    # VAL-HEALTH-001: any service observation losing health/readiness fails.
    for obs in svc.get("observations", []):
        if obs.get("health") in ("unhealthy", "unknown"):
            raise AcceptanceFailure(
                f"service {obs.get('service_ref')} health lost", EXIT_VALIDATION_FAILURE
            )
        if obs.get("readiness") in ("not_ready", "unknown"):
            raise AcceptanceFailure(
                f"service {obs.get('service_ref')} readiness lost", EXIT_VALIDATION_FAILURE
            )
    if svc.get("restart_delta_zero") is not True:
        raise AcceptanceFailure("service restart delta not zero", EXIT_VALIDATION_FAILURE)
    if svc.get("ollama_unloaded_all_phases") is not True:
        raise AcceptanceFailure("Ollama loaded during measurement", EXIT_VALIDATION_FAILURE)
    incidents = svc.get("incidents", {})
    for k, v in incidents.items():
        if v is True:
            raise AcceptanceFailure(f"service incident detected: {k}",
                                    EXIT_VALIDATION_FAILURE)

    # VAL-OVERLAP-001
    for ov in evidence.get("workloads", {}).get("overlaps", []):
        if ov.get("overlap_ms", 0) < MINIMUM_OVERLAP_MS:
            raise AcceptanceFailure(f"{ov.get('phase')} overlap below 5 s",
                                    EXIT_VALIDATION_FAILURE)

    # VAL-OUTPUT-001
    wl = evidence.get("workloads", {})
    if len(wl.get("whisper_outputs", [])) != 3:
        raise AcceptanceFailure("not exactly three Whisper outputs", EXIT_VALIDATION_FAILURE)
    for o in wl.get("whisper_outputs", []):
        if not o.get("job_done") or not o.get("input_hash_match") or o.get("raw_payload_present"):
            raise AcceptanceFailure("Whisper output invalid", EXIT_VALIDATION_FAILURE)
    if len(wl.get("dots_outputs", [])) != 2:
        raise AcceptanceFailure("not exactly two Dots outputs", EXIT_VALIDATION_FAILURE)
    for o in wl.get("dots_outputs", []):
        if not o.get("nonempty_bytes") or not o.get("playable_probe") or o.get("raw_audio_present"):
            raise AcceptanceFailure("Dots output invalid", EXIT_VALIDATION_FAILURE)

    # VAL-CLEANUP-001
    cl = evidence.get("cleanup_and_rollback", {})
    if cl.get("unapproved_resource_mutation_attempted") is True:
        raise AcceptanceFailure("unapproved cleanup mutation attempted",
                                EXIT_CLEANUP_ROLLBACK_FAILURE)
    if cl.get("adjusted_drift_mib", 10**9) > CLEANUP_DRIFT_LIMIT_MIB:
        raise AcceptanceFailure("cleanup drift exceeds limit", EXIT_CLEANUP_ROLLBACK_FAILURE)
    if cl.get("app_healthy_after_cleanup") is not True:
        raise AcceptanceFailure("app not healthy after cleanup", EXIT_CLEANUP_ROLLBACK_FAILURE)
    if cl.get("production_backends_after_cleanup", {}) != {"whisper": "mock", "diarize": "mock"}:
        raise AcceptanceFailure("production backends not mock after cleanup",
                                EXIT_CLEANUP_ROLLBACK_FAILURE)

    # VAL-STATUS-001 / VAL-MODE-001
    run = evidence.get("run", {})
    overall = evidence.get("overall", {})
    if run.get("status") != overall.get("status"):
        raise AcceptanceFailure("run.status != overall.status", EXIT_VALIDATION_FAILURE)
    if overall.get("acceptance_pass") and run.get("mode") != "live":
        raise AcceptanceFailure("only a passing live run may set acceptance_pass",
                                EXIT_VALIDATION_FAILURE)
    if run.get("mode") in ("discovery", "mock") and overall.get("acceptance_pass"):
        raise AcceptanceFailure("discovery/mock cannot be acceptance_pass",
                                EXIT_VALIDATION_FAILURE)

    # VAL-REDACT-001 / TEST-AIGPU1-007 candidate binding
    cand = evidence.get("candidate", {})
    if overall.get("acceptance_pass") and (
        not cand.get("source_commit")
        or not cand.get("worker_image_digest")
        or not cand.get("compose_redacted_render_digest")
    ):
        raise AcceptanceFailure("live pass missing exact candidate binding",
                                EXIT_VALIDATION_FAILURE)
    if evidence.get("redaction", {}).get("raw_sensitive_payloads_present") is True:
        raise AcceptanceFailure("raw sensitive payloads present in evidence",
                                EXIT_REDACTION_FAILURE)


def _wall_to_ns(wall: str) -> int:
    from datetime import datetime, timezone

    # Accept RFC3339 with up to 9 fractional digits and a trailing Z.
    normalized = wall.replace("Z", "+00:00")
    # Truncate fractional seconds to microseconds for fromisoformat compatibility.
    if "." in normalized:
        head, _, frac = normalized.partition(".")
        frac = (frac[:6]).ljust(6, "0")
        normalized = f"{head}.{frac}+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1e9)


def validate_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Schema + semantic validation; returns sanitized verdict dict.

    Semantic rules run first so the specific fail-closed exit classes (e.g.
    cleanup/rollback = 7, redaction = 6) win over the generic schema const
    violation (2) when both apply.
    """
    validate_semantic_rules(evidence)
    validate_schema(evidence)
    return sanitize({
        "verdict": "PASS",
        "schema_version": "1.0.0",
        "evidence_class": evidence.get("evidence_class"),
        "mode": evidence.get("run", {}).get("mode"),
        "acceptance_eligible": evidence.get("run", {}).get("acceptance_eligible"),
        "acceptance_pass": evidence.get("overall", {}).get("acceptance_pass"),
        "failed_requirements": evidence.get("overall", {}).get("failed_requirements", []),
    })


# ---------------------------------------------------------------------------
# Discovery (bounded allowlist, redacted) -- BUG-AIGPU1-002
# ---------------------------------------------------------------------------
ALLOWED_DISCOVERY = {
    ("nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"),
    ("docker", "compose", "ps", "--format", "json"),
    ("docker", "inspect", "--format", "{{json .State.Health}}"),
}


def discovery(adapter: AcceptanceAdapter | None = None) -> dict[str, Any]:
    """Bounded read-only discovery; only opaque, non-sensitive fields survive."""
    adp = adapter or MockAdapter()
    seen = {}

    def runner(command):
        cmd = tuple(command)
        if cmd not in ALLOWED_DISCOVERY:
            raise AcceptanceFailure(
                f"non-allowlisted discovery command: {cmd}",
                exit_class=EXIT_ADAPTER_ERROR,
            )
        out = adp.run_read_only(list(command), timeout_s=10)
        # Bounded parse: only the opaque fields we enumerate are kept. Any
        # residual private path/name/transcript/runtime id is redacted before
        # it can enter the evidence shape (BUG-AIGPU1-002).
        return redact_scalar(out)

    try:
        gpu_raw = runner(["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                          "--format=csv,noheader,nounits"])
        compose_raw = runner(["docker", "compose", "ps", "--format", "json"])
    except AcceptanceFailure:
        raise
    except Exception as exc:  # timeout / malformed / missing tool
        raise AcceptanceFailure(
            f"read-only discovery failed: {exc}", exit_class=EXIT_UNAVAILABLE
        ) from exc

    fields = [f.strip() for f in gpu_raw.split(",")] if gpu_raw else []
    raw_model = fields[0] if fields else "unknown"
    # The model name is an opaque device label; only a safe device-name pattern
    # may enter evidence. Anything containing a private path, secret, transcript
    # fragment, runtime id, or free-form text is replaced (BUG-AIGPU1-002).
    model = raw_model if raw_model in SAFE_GPU_MODELS else "unknown"
    gpu = {
        "model": model,
        "memory_total_mib": int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else None,
        "memory_used_mib": int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else None,
    }
    try:
        services = json.loads(compose_raw) if compose_raw else []
    except (ValueError, TypeError):
        services = []
    states = sorted({str(s.get("State", "unknown")) for s in services}) \
        if isinstance(services, list) else []
    compose = {
        "service_count": len(services) if isinstance(services, list) else 0,
        "states": [state if state in SAFE_SERVICE_STATES else "unknown" for state in states],
    }
    seen.update(gpu=gpu, compose=compose)
    whisper_backend = os.getenv("WHISPER_BACKEND", "unset")
    diarize_backend = os.getenv("DIARIZE_BACKEND", "unset")
    evidence = {
        "mode": "discovery",
        "read_only": True,
        "gpu": sanitize(gpu),
        "compose": sanitize(compose),
        "production_backends": {
            "whisper": whisper_backend if whisper_backend in SAFE_BACKENDS else "unknown",
            "diarize": diarize_backend if diarize_backend in SAFE_BACKENDS else "unknown",
        },
    }
    # Final deep redaction pass before emission.
    return sanitize(evidence)


# ---------------------------------------------------------------------------
# Plan / mock / execute
# ---------------------------------------------------------------------------
def plan() -> dict[str, Any]:
    """Local schema/config validation only; no external command."""
    schema = load_canonical_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    sample = build_mock_evidence()
    validate_schema(sample)  # prove the harness can build a canonical instance
    return sanitize({
        "verdict": "PASS",
        "mode": "plan",
        "canonical_schema": str(CANONICAL_SCHEMA_PATH),
        "config": {
            "nominal_interval_ms": NOMINAL_INTERVAL_MS,
            "maximum_gap_ms": MAX_GAP_MS,
            "baseline_minimum_ms": BASELINE_MINIMUM_MS,
            "dots_resident_minimum_ms": DOTS_RESIDENT_MINIMUM_MS,
            "post_workload_minimum_ms": POST_WORKLOAD_MINIMUM_MS,
            "active_overlap_minimum_ms": MINIMUM_OVERLAP_MS,
            "cleanup_drift_limit_mib": CLEANUP_DRIFT_LIMIT_MIB,
        },
    })


def mock_run(adapter: MockAdapter | None = None) -> dict[str, Any]:
    """Deterministic offline acceptance with injected adapters and fake clocks."""
    adp = adapter or MockAdapter()
    evidence = build_mock_evidence()
    # Exercise the adapter: a failed check transitions mock to a failure so the
    # harness never silently reports a pass.
    if not adp.checks.get("app_healthy"):
        evidence["services"]["observations"][0]["health"] = "unhealthy"
        evidence["services"]["status"] = "fail"
    if not adp.checks.get("outputs_valid"):
        evidence["workloads"]["whisper_outputs"][0]["job_done"] = False
    if not adp.checks.get("cleanup_drift_ok"):
        evidence["cleanup_and_rollback"]["adjusted_drift_mib"] = 513
        evidence["cleanup_and_rollback"]["status"] = "fail"
    if not adp.checks.get("mock_backends_restored"):
        evidence["cleanup_and_rollback"]["production_backends_after_cleanup"] = {
            "whisper": "real", "diarize": "mock"
        }
    return validate_evidence(evidence)


def execute(adapter: AcceptanceAdapter | None = None) -> dict[str, Any]:
    """Reserved authorized live workflow. Refuses unless fully authorized."""
    adp = adapter or MockAdapter()
    # The sanitized harness never ships a live adapter. Without the same-host
    # discovery bundle, scoped authorization record, immutable candidate ids,
    # and private fixture binding, this fails closed as unauthorized.
    try:
        adp.submit_workload("whisper_cold")
    except AcceptanceFailure as exc:
        if exc.exit_class == EXIT_UNAUTHORIZED:
            raise AcceptanceFailure(
                "live acceptance requires explicit Peter authorization, the "
                "same-host discovery bundle, immutable candidate identifiers, "
                "and the private fixture binding",
                exit_class=EXIT_UNAUTHORIZED,
            ) from exc
        raise
    raise AcceptanceFailure(
        "live execution is disabled in the sanitized harness",
        exit_class=EXIT_UNAUTHORIZED,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None, adapter: AcceptanceAdapter | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sanitized AI-GPU-1 acceptance harness (canonical contract).",
        prog="ai_gpu_acceptance",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true", help="validate schema/config locally")
    group.add_argument("--discover", action="store_true", help="explicit read-only discovery")
    group.add_argument("--validate", type=Path, metavar="EVIDENCE_JSON",
                       help="validate an existing redacted evidence instance")
    group.add_argument("--mock", action="store_true", help="deterministic offline acceptance")
    group.add_argument("--execute", action="store_true",
                       help="reserved; authorized live workflow only")
    args = parser.parse_args(argv)

    try:
        if args.plan:
            result = plan()
        elif args.discover:
            result = discovery(adapter or LocalReadOnlyAdapter())
        elif args.validate is not None:
            data = json.loads(args.validate.read_text(encoding="utf-8"))
            result = validate_evidence(data)
        elif args.mock:
            result = mock_run(adapter if isinstance(adapter, MockAdapter) else None)
        elif args.execute:
            result = execute(adapter)
        else:  # pragma: no cover - mutually exclusive group makes this unreachable
            parser.print_usage(sys.stderr)
            return EXIT_VALIDATION_FAILURE
    except AcceptanceFailure as exc:
        print(json.dumps({"verdict": "FAIL", "error": sanitize(exc.message),
                          "exit_class": _class_name(exc.exit_class)},
                         sort_keys=True), file=sys.stderr)
        return exc.exit_class
    except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"verdict": "FAIL", "error": sanitize(str(exc)),
                          "exit_class": _class_name(EXIT_ADAPTER_ERROR)},
                         sort_keys=True), file=sys.stderr)
        return EXIT_ADAPTER_ERROR

    print(json.dumps(result, sort_keys=True))
    return EXIT_SUCCESS


def _class_name(code: int) -> str:
    return {
        EXIT_SUCCESS: "success",
        EXIT_VALIDATION_FAILURE: "validation_failure",
        EXIT_UNAVAILABLE: "unavailable",
        EXIT_UNAUTHORIZED: "unauthorized",
        EXIT_ADAPTER_ERROR: "adapter_error",
        EXIT_REDACTION_FAILURE: "redaction_failure",
        EXIT_CLEANUP_ROLLBACK_FAILURE: "cleanup_or_rollback_failure",
    }.get(code, "unknown")


if __name__ == "__main__":
    raise SystemExit(main())
