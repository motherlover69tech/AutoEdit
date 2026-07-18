import json
import pytest

from scripts.ai_gpu_acceptance import AcceptanceFailure, Sample, discovery, sanitize, validate_acceptance, validate_phase_markers, validate_samples


def evidence():
    samples = [
        {"timestamp_ms": timestamp, "total_mib": 32768, "used_mib": 12000, "phase": "baseline" if timestamp < 10000 else "post"}
        for timestamp in range(0, 80001, 250)
    ]
    markers = {
        "baseline": {"start_ms": 0, "end_ms": 10000},
        "resident": {"start_ms": 10000, "end_ms": 20000},
        "cold": {"start_ms": 20000, "end_ms": 30000},
        "active": {"start_ms": 30000, "end_ms": 40000, "dots_start_ms": 31000, "dots_end_ms": 39000, "whisper_start_ms": 32000, "whisper_end_ms": 38000},
        "active_repeat": {"start_ms": 40000, "end_ms": 50000, "dots_start_ms": 41000, "dots_end_ms": 49000, "whisper_start_ms": 42000, "whisper_end_ms": 48000},
        "post": {"start_ms": 50000, "end_ms": 80000},
    }
    return {
        "samples": samples,
        "phase_markers": markers,
        "health": {"app": True, "dots": True, "worker_ready": True, "ollama_unloaded": True, "restarts": 0},
        "outputs": {"dots_first": True, "dots_second": True, "whisper_cold": True, "whisper_repeat": True},
        "cleanup": {"memory_drift_mib": 100, "app_healthy": True},
        "backends": {"whisper": "mock", "diarize": "mock"},
    }


def test_valid_redacted_acceptance_summary():
    result = validate_acceptance(evidence())
    assert result["verdict"] == "PASS"
    assert result["required_headroom_mib"] == 3277


@pytest.mark.parametrize("change,needle", [
    (lambda e: (e["samples"].__setitem__(1, {**e["samples"][1], "timestamp_ms": 1000}), e["samples"].__setitem__(2, {**e["samples"][2], "timestamp_ms": 1250})), "gap"),
    (lambda e: e["health"].__setitem__("unknown_gpu_processes", True), "unknown"),
    (lambda e: e["health"].__setitem__("restarts", 1), "restart"),
    (lambda e: e["health"].__setitem__("app", False), "health"),
    (lambda e: e["health"].__setitem__("ollama_unloaded", False), "ollama"),
    (lambda e: e["outputs"].__setitem__("dots_first", False), "output"),
    (lambda e: e["phase_markers"].pop("active_repeat"), "marker"),
    (lambda e: e["phase_markers"]["active"]["dots_end_ms"].__class__, "never"),
    (lambda e: e["cleanup"].__setitem__("memory_drift_mib", 513), "cleanup"),
    (lambda e: e["backends"].__setitem__("whisper", "real"), "mock"),
])
def test_invalid_acceptance_conditions_fail_closed(change, needle):
    current = evidence()
    if needle == "never":
        current["phase_markers"]["active"]["dots_end_ms"] = 34000
        current["phase_markers"]["active"]["whisper_end_ms"] = 33000
        needle = "overlap"
    else:
        change(current)
    with pytest.raises(AcceptanceFailure, match=needle):
        validate_acceptance(current)


def test_process_accounting_and_invalid_memory_are_rejected():
    sample = Sample(0, 100, 50, "baseline")
    validate_samples([sample])
    with pytest.raises(AcceptanceFailure, match="per-process"):
        validate_samples([Sample(0, 100, 50, "baseline", (type("P", (), {"pid": 0, "name": "", "used_mib": -1})(),))])


def test_marker_clock_reconciliation_rejects_short_post():
    current = evidence()
    current["phase_markers"]["post"]["end_ms"] = 60000
    with pytest.raises(AcceptanceFailure, match="30 seconds"):
        validate_phase_markers(current["phase_markers"], [Sample(item["timestamp_ms"], 32768, 1000, item["phase"]) for item in current["samples"]])


def test_discovery_redacts_private_paths_transcript_names_and_runtime_ids():
    """BUG-AIGPU1-002: discovery output must never leak private strings."""
    def runner(command):
        if command[0] == "nvidia-smi":
            # A hostile gpu line: private media path, person name, transcript text,
            # runtime id, and a secret-bearing value mixed into the output.
            return "/private/media/angle.mp4,Alicespc transcript=hello-world runtime-id-99 token=TOKEN123"
        return '[{"Name":"autoedit","State":"running"}]'
    result = discovery(runner)
    encoded = json.dumps(result, sort_keys=True)
    # None of the private fragments survive the bounded allowlist + redaction.
    assert "/private/media/angle.mp4" not in encoded
    assert "Alice" not in encoded
    assert "transcript=hello-world" not in encoded
    assert "runtime-id-99" not in encoded
    assert "TOKEN123" not in encoded
    # Only bounded, non-sensitive structured fields remain.
    assert set(result["compose"]["states"]) == {"running"}
    assert result["compose"]["service_count"] == 1
    assert "gpu" in result and "production_backends" in result


def test_sanitize_redacts_private_path_and_runtime_id_strings():
    """Direct redaction regression for arbitrary private content (BUG-AIGPU1-002)."""
    payload = {"note": "/home/peter/secret-clip.mov", "id": "proc-id-77=abc", "text": "transcript=ConfidentialName"}
    cleaned = sanitize(payload)
    encoded = json.dumps(cleaned, sort_keys=True)
    assert "/home/peter/secret-clip.mov" not in encoded
    assert "proc-id-77" not in encoded
    assert "ConfidentialName" not in encoded
    # Secret-keyed values are still removed by key, not echoed.
    assert "credential" not in encoded

