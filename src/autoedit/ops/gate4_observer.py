"""Read-only GATE-4 observation validation.

This module cannot execute commands, contact services, launch workloads, or clean
resources. It validates a rendered Compose projection and an authenticated,
append-only stream of observations produced at those service boundaries.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from autoedit.ai.gpu_measurement import GPUSample, summarize_gpu_acceptance, validate_sampling


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
_PHASE_MINIMUM_MS = {"baseline": 10_000, "dots_resident": 10_000, "post_workload": 30_000}
_METADATA_FIELDS = {
    "source_commit",
    "worker_image_digest",
    "compose_render_sha256",
    "authorization_ref",
    "fixture_ref",
}
_EVENT_FIELDS = {
    "phase": {"sequence", "type", "phase", "start_ms", "end_ms", "observation_mac"},
    "gpu_sample": {
        "sequence", "type", "phase", "timestamp_ms", "total_mib", "used_mib",
        "process_used_mib", "unknown_processes", "observation_mac",
    },
    "service_boundary": {
        "sequence", "type", "phase", "app_healthy", "dots_healthy", "worker_ready",
        "restart_delta", "ollama_loaded_models", "incident_codes", "observation_mac",
    },
    "whisper_output": {
        "sequence", "type", "phase", "job_state", "input_hash_match",
        "aligned_word_count", "speaker_count", "observation_mac",
    },
    "dots_output": {
        "sequence", "type", "phase", "api_status", "submitted_after_mtime_ns",
        "output_mtime_ns", "stable_mtime_observations", "nonempty_bytes", "playable",
        "observation_mac",
    },
    "overlap": {
        "sequence", "type", "phase", "dots_start_ms", "dots_end_ms",
        "whisper_start_ms", "whisper_end_ms", "observation_mac",
    },
    "cleanup": {
        "sequence", "type", "baseline_idle_mib", "post_cleanup_idle_mib", "app_healthy",
        "whisper_backend", "diarize_backend", "prior_artifact_unchanged",
        "prior_cut_unchanged", "observation_mac",
    },
}
_SHA256_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")


class Gate4ObservationError(ValueError):
    """Observed GATE-4 data is incomplete, unauthenticated, or failing."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def authenticate_observations(
    events: Sequence[Mapping[str, Any]],
    observation_key: bytes,
    *,
    compose: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Bind candidate context and events for a trusted collector to persist."""
    _validate_key(observation_key)
    signed: list[dict[str, Any]] = []
    previous_mac = _context_mac(compose, metadata, observation_key)
    for event in events:
        item = deepcopy(dict(event))
        item.pop("observation_mac", None)
        mac = hmac.new(observation_key, previous_mac + _canonical(item), hashlib.sha256).hexdigest()
        item["observation_mac"] = mac
        signed.append(item)
        previous_mac = bytes.fromhex(mac)
    return signed


def _validate_key(observation_key: bytes) -> None:
    if not isinstance(observation_key, bytes) or len(observation_key) < 32:
        raise Gate4ObservationError("an external observation authentication key is required")


def _context_mac(
    compose: Mapping[str, Any], metadata: Mapping[str, Any], observation_key: bytes
) -> bytes:
    context = {"compose": dict(compose), "metadata": dict(metadata)}
    return hmac.new(
        observation_key, b"gate4-context-v1\0" + _canonical(context), hashlib.sha256
    ).digest()


def _verify_event_chain(
    events: Sequence[Mapping[str, Any]],
    observation_key: bytes,
    *,
    compose: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> None:
    _validate_key(observation_key)
    previous_mac = _context_mac(compose, metadata, observation_key)
    previous_sequence = -1
    for raw in events:
        if not isinstance(raw, Mapping):
            raise Gate4ObservationError("observation must be an object")
        item = dict(raw)
        event_type = item.get("type")
        allowed = _EVENT_FIELDS.get(event_type)
        if allowed is None:
            raise Gate4ObservationError("unknown observation type")
        unknown = set(item) - allowed
        missing = allowed - set(item)
        if unknown:
            raise Gate4ObservationError(f"unknown field in {event_type} observation")
        if missing:
            raise Gate4ObservationError(f"missing field in {event_type} observation")
        sequence = item.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= previous_sequence:
            raise Gate4ObservationError("observation sequence must increase")
        supplied = item.pop("observation_mac")
        expected = hmac.new(
            observation_key, previous_mac + _canonical(item), hashlib.sha256
        ).hexdigest()
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
            raise Gate4ObservationError("observation authentication failed")
        previous_mac = bytes.fromhex(supplied)
        previous_sequence = sequence


def _compose_port_is_loopback(port: Any) -> bool:
    if isinstance(port, str):
        return port.startswith("127.0.0.1:")
    return isinstance(port, Mapping) and port.get("host_ip") == "127.0.0.1"


def _volume_properties(volume: Any) -> tuple[str | None, bool]:
    if isinstance(volume, Mapping):
        return volume.get("target"), bool(volume.get("read_only"))
    if isinstance(volume, str):
        parts = volume.split(":")
        return (parts[1] if len(parts) > 1 else None, parts[-1] == "ro")
    return None, False


def _validate_compose(compose: Mapping[str, Any]) -> None:
    services = compose.get("services")
    if not isinstance(services, Mapping):
        raise Gate4ObservationError("Compose services are missing")
    app, worker = services.get("app"), services.get("whisperx")
    if not isinstance(app, Mapping) or not isinstance(worker, Mapping):
        raise Gate4ObservationError("Compose app or whisperx service is missing")
    if app.get("network_mode") != "host":
        raise Gate4ObservationError("Compose app must retain host networking")
    environment = app.get("environment")
    if not isinstance(environment, Mapping) or environment.get("WHISPER_BACKEND") != "mock" or environment.get("DIARIZE_BACKEND") != "mock":
        raise Gate4ObservationError("Compose application backends must remain mock")
    ports = worker.get("ports")
    if not isinstance(ports, list) or not ports or not all(_compose_port_is_loopback(port) for port in ports):
        raise Gate4ObservationError("whisperx ports must be loopback-only")
    volumes = [_volume_properties(volume) for volume in worker.get("volumes", [])]
    if ("/data", True) not in volumes:
        raise Gate4ObservationError("whisperx media mount must be read-only")
    if not any(target == "/models" and not read_only for target, read_only in volumes):
        raise Gate4ObservationError("whisperx model cache must be persistent")
    if not isinstance(worker.get("healthcheck"), Mapping):
        raise Gate4ObservationError("whisperx readiness healthcheck is required")
    worker_env = worker.get("environment")
    if not isinstance(worker_env, Mapping) or str(worker_env.get("WHISPERX_MAX_CONCURRENT_JOBS")) != "1":
        raise Gate4ObservationError("whisperx concurrency must be exactly one")


def _validate_metadata(metadata: Mapping[str, Any]) -> None:
    unknown = set(metadata) - _METADATA_FIELDS
    missing = _METADATA_FIELDS - set(metadata)
    if unknown:
        raise Gate4ObservationError("unknown metadata field")
    if missing:
        raise Gate4ObservationError("missing exact-candidate metadata")
    if not _COMMIT.fullmatch(str(metadata["source_commit"])):
        raise Gate4ObservationError("source commit is invalid")
    for key in ("worker_image_digest", "compose_render_sha256"):
        if not _SHA256_REF.fullmatch(str(metadata[key])):
            raise Gate4ObservationError(f"{key} is invalid")
    if not metadata["authorization_ref"] or not metadata["fixture_ref"]:
        raise Gate4ObservationError("authorization and fixture references are required")


def evaluate_gate4_observations(
    compose: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    *,
    observation_key: bytes,
) -> dict[str, Any]:
    """Derive GATE-4 from authenticated observations without live operations."""
    # Authenticate the exact candidate context before interpreting it. A valid
    # event stream cannot be replayed against edited Compose or metadata.
    _verify_event_chain(
        events, observation_key, compose=compose, metadata=metadata
    )
    _validate_metadata(metadata)
    _validate_compose(compose)
    copied = [dict(event) for event in events]

    phases = [event for event in copied if event["type"] == "phase"]
    if [event.get("phase") for event in phases] != list(REQUIRED_PHASES):
        raise Gate4ObservationError("required phase order or coverage is invalid")
    phase_by_name: dict[str, tuple[int, int]] = {}
    previous_end = -1
    for event in phases:
        start, end = event["start_ms"], event["end_ms"]
        if not isinstance(start, int) or not isinstance(end, int) or end <= start or start <= previous_end:
            raise Gate4ObservationError("phase markers overlap, invert, or repeat")
        duration = end - start
        if duration < _PHASE_MINIMUM_MS.get(event["phase"], 1):
            raise Gate4ObservationError(f"{event['phase']} phase is too short")
        phase_by_name[event["phase"]] = (start, end)
        previous_end = end

    sample_events = [event for event in copied if event["type"] == "gpu_sample"]
    samples = []
    for event in sample_events:
        if event["phase"] not in phase_by_name:
            raise Gate4ObservationError("GPU sample phase is unknown")
        start, end = phase_by_name[event["phase"]]
        if not start <= event["timestamp_ms"] <= end:
            raise Gate4ObservationError("GPU sample lies outside its phase")
        if event["unknown_processes"] is not False:
            raise Gate4ObservationError("unknown GPU process invalidates the run")
        samples.append(GPUSample(
            event["timestamp_ms"], event["total_mib"], event["used_mib"], event["phase"],
            process_used_mib=tuple(event["process_used_mib"]),
        ))
    try:
        validate_sampling(samples, max_interval_ms=500)
        vram = summarize_gpu_acceptance(samples)
    except ValueError as exc:
        raise Gate4ObservationError(f"GPU sampler gap or accounting failure: {exc}") from exc
    if vram["verdict"] != "PASS":
        raise Gate4ObservationError("GPU headroom requirement failed")

    boundaries = [event for event in copied if event["type"] == "service_boundary"]
    if Counter(event["phase"] for event in boundaries) != Counter(REQUIRED_PHASES):
        raise Gate4ObservationError("one service boundary per phase is required")
    for event in boundaries:
        if not event["app_healthy"] or not event["dots_healthy"]:
            raise Gate4ObservationError("application or Dots health was lost")
        if event["phase"] not in {"baseline", "dots_resident"} and not event["worker_ready"]:
            raise Gate4ObservationError("worker readiness was lost")
        if event["restart_delta"] != 0:
            raise Gate4ObservationError("unexpected service restart")
        if event["ollama_loaded_models"] != 0:
            raise Gate4ObservationError("Ollama must remain unloaded")
        if event["incident_codes"]:
            raise Gate4ObservationError("service incident invalidates the run")

    whisper = [event for event in copied if event["type"] == "whisper_output"]
    expected_whisper = {"whisper_cold", "active_overlap_1", "active_overlap_2"}
    if {event["phase"] for event in whisper} != expected_whisper or len(whisper) != 3:
        raise Gate4ObservationError("exactly three Whisper outputs are required")
    if any(
        event["job_state"] != "done" or event["input_hash_match"] is not True
        or event["aligned_word_count"] <= 0 or event["speaker_count"] != 2
        for event in whisper
    ):
        raise Gate4ObservationError("Whisper output validation failed")

    dots = [event for event in copied if event["type"] == "dots_output"]
    expected_active = {"active_overlap_1", "active_overlap_2"}
    if {event["phase"] for event in dots} != expected_active or len(dots) != 2:
        raise Gate4ObservationError("exactly two Dots outputs are required")
    if any(
        event["api_status"] != "completed"
        or event["output_mtime_ns"] <= event["submitted_after_mtime_ns"]
        or event["stable_mtime_observations"] < 2
        or event["nonempty_bytes"] <= 0
        or event["playable"] is not True
        for event in dots
    ):
        raise Gate4ObservationError("Dots output mtime or playable validation failed")

    overlaps = [event for event in copied if event["type"] == "overlap"]
    if {event["phase"] for event in overlaps} != expected_active or len(overlaps) != 2:
        raise Gate4ObservationError("exactly two active overlap observations are required")
    for event in overlaps:
        overlap_ms = min(event["dots_end_ms"], event["whisper_end_ms"]) - max(
            event["dots_start_ms"], event["whisper_start_ms"]
        )
        if overlap_ms < 5_000:
            raise Gate4ObservationError("active workload overlap is below five seconds")

    cleanup = [event for event in copied if event["type"] == "cleanup"]
    if len(cleanup) != 1:
        raise Gate4ObservationError("exactly one cleanup observation is required")
    cleanup_event = cleanup[0]
    if cleanup_event["post_cleanup_idle_mib"] - cleanup_event["baseline_idle_mib"] > 512:
        raise Gate4ObservationError("cleanup GPU drift exceeds 512 MiB")
    if (
        cleanup_event["app_healthy"] is not True
        or cleanup_event["whisper_backend"] != "mock"
        or cleanup_event["diarize_backend"] != "mock"
        or cleanup_event["prior_artifact_unchanged"] is not True
        or cleanup_event["prior_cut_unchanged"] is not True
    ):
        raise Gate4ObservationError("cleanup, mock backend, or preservation check failed")

    return {
        "verdict": "PASS",
        "acceptance_source": "authenticated_observed_boundaries",
        "candidate": dict(metadata),
        "compose": {
            "app_host_network": True,
            "worker_loopback_only": True,
            "media_read_only": True,
            "queue_concurrency": 1,
            "production_backends": {"whisper": "mock", "diarize": "mock"},
        },
        "phases": list(REQUIRED_PHASES),
        "workloads": {"whisper": 3, "dots": 2, "overlaps": 2},
        "vram": {
            "total_mib": vram["total_mib"],
            "peak_used_mib": vram["peak_used_mib"],
            "used_column_peak_mib": vram["used_column_peak_mib"],
            "minimum_free_mib": vram["minimum_free_mib"],
            "required_headroom_mib": vram["required_headroom_mib"],
            "accounting_anomalies": vram["used_process_discrepancy_count"],
        },
        "observation_count": len(copied),
    }


__all__ = [
    "Gate4ObservationError",
    "REQUIRED_PHASES",
    "authenticate_observations",
    "evaluate_gate4_observations",
]
