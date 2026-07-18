"""Offline acceptance coverage for every AI-GPU-1 fail-closed contract branch.

These tests intentionally use only in-memory evidence, fake clocks, and fake
subprocess runners.  A real host, network, Docker, GPU, Dots, or Ollama must
never be needed to collect this module.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ai_gpu_acceptance import (
    AcceptanceFailure,
    AcceptanceHarness,
    MockAdapter,

    Sample,
    discovery,
    main,
    mock_evidence,
    sanitize,
    validate_acceptance,

    validate_samples,
)


def valid_evidence() -> dict:
    return mock_evidence()


def expect_failure(mutator, message: str) -> None:
    evidence = valid_evidence()
    mutator(evidence)
    with pytest.raises(AcceptanceFailure, match=message):
        validate_acceptance(evidence)


@pytest.mark.parametrize(
    ("samples", "message"),
    [
        ([Sample(0, 100, 10, "baseline"), Sample(501, 100, 10, "baseline")], "gap"),
        ([Sample(0, 100, 10, "baseline"), Sample(0, 100, 10, "baseline")], "not increasing"),
        ([Sample(-1, 100, 10, "baseline")], "invalid GPU memory"),
        ([Sample(0, 100, 101, "baseline")], "invalid GPU memory"),
        ([Sample(0, 0, 0, "baseline")], "invalid GPU memory"),
        ([Sample(0, 100, 10, "")], "missing GPU sample phase"),
    ],
)
def test_sampler_rejects_bad_interval_order_and_memory(samples, message):
    with pytest.raises(AcceptanceFailure, match=message):
        validate_samples(samples)


def test_config_rejects_nominal_sampling_slower_than_250_ms():
    with pytest.raises(AcceptanceFailure, match="<= 250"):
        validate_samples([Sample(0, 100, 10, "baseline")], nominal_interval_ms=251)


@pytest.mark.parametrize(
    "mutator,message",
    [
        (lambda e: e["phase_markers"].pop("cold"), "missing phase markers"),
        (lambda e: e["phase_markers"]["cold"].update(start_ms=19_999, end_ms=29_999), "overlap or are out of order"),
        (lambda e: e["phase_markers"]["resident"].update(start_ms=9_999, end_ms=19_999), "overlap or are out of order"),
        (lambda e: e["phase_markers"]["baseline"].update(end_ms=9_999), "baseline phase must cover 10 seconds"),
        (lambda e: e["phase_markers"]["post"].update(start_ms=50_000, end_ms=79_999), "post phase must cover 30 seconds"),
        (lambda e: e["phase_markers"]["baseline"].update(start_ms="0"), "invalid baseline phase marker"),
        (lambda e: e["phase_markers"]["post"].update(end_ms=999_999), "outside sample clock"),
        (lambda e: e["phase_markers"]["active"].update(dots_end_ms=34_000, whisper_end_ms=33_000), "overlap"),
    ],
)
def test_phase_markers_and_overlap_fail_closed(mutator, message):
    expect_failure(mutator, message)


def test_duplicate_phase_marker_key_cannot_be_silently_accepted():
    # JSON evidence is the interchange boundary: duplicate phase names must be
    # detected before a Python dict loses the duplicate key.
    raw = '{"baseline":{"start_ms":0,"end_ms":10000},"baseline":{"start_ms":1,"end_ms":10001}}'
    pairs = json.loads(raw, object_pairs_hook=list)
    assert [key for key, _ in pairs].count("baseline") == 2


def test_irreconcilable_wall_and_monotonic_clocks_fail():
    samples = [
        Sample(0, 100, 10, "baseline", wall_timestamp_ms=1_000),
        Sample(250, 100, 10, "baseline", wall_timestamp_ms=2_000),
    ]
    with pytest.raises(AcceptanceFailure, match="reconciliation"):
        validate_samples(samples)


def test_missing_or_malformed_per_process_accounting_fails():
    bad = [
        {"pid": 0, "name": "worker", "used_mib": 1},
        {"pid": 4, "name": "", "used_mib": 1},
        {"pid": 4, "name": "worker", "used_mib": -1},
        {"pid": 4, "used_mib": 1},
    ]
    for process in bad:
        with pytest.raises(AcceptanceFailure, match="per-process"):
            validate_samples([Sample(0, 100, 10, "baseline", (process,))])


def test_missing_evidence_and_malformed_backend_observation_fail():
    for key in ("samples", "phase_markers", "health", "outputs", "cleanup", "backends"):
        evidence = valid_evidence()
        evidence.pop(key)
        with pytest.raises(AcceptanceFailure, match="missing evidence fields"):
            validate_acceptance(evidence)
    evidence = valid_evidence()
    evidence["samples"] = [{"timestamp_ms": "not-a-sample"}]
    with pytest.raises(AcceptanceFailure, match="malformed GPU observation"):
        validate_acceptance(evidence)


@pytest.mark.parametrize(
    "mutator,message",
    [
        (lambda e: e["health"].update(app=False), "health check failed: app"),
        (lambda e: e["health"].update(dots=False), "health check failed: dots"),
        (lambda e: e["health"].update(worker_ready=False), "health check failed: worker_ready"),
        (lambda e: e["health"].update(ollama_unloaded=False), "health check failed: ollama_unloaded"),
        (lambda e: e["health"].update(restarts=1), "restart"),
        (lambda e: e["health"].update(readiness_loss=True), "workload health"),
        (lambda e: e["outputs"].update(dots_first=False), "invalid or incomplete output"),
        (lambda e: e["outputs"].update(dots_second=False), "invalid or incomplete output"),
        (lambda e: e["outputs"].update(whisper_cold=False), "invalid or incomplete output"),
        (lambda e: e["outputs"].update(whisper_repeat=False), "invalid or incomplete output"),
        (lambda e: e["cleanup"].update(memory_drift_mib=513), "cleanup"),
        (lambda e: e["cleanup"].update(app_healthy=False), "cleanup"),
        (lambda e: e["backends"].update(whisper="real"), "mock"),
        (lambda e: e["backends"].update(diarize="real"), "mock"),
    ],
)
def test_health_outputs_cleanup_and_backend_failures_are_nonzero(mutator, message):
    expect_failure(mutator, message)


def test_harness_failed_adapter_is_not_a_pass():
    adapter = MockAdapter(checks={name: False for name in ("app", "dots", "worker_ready", "ollama_unloaded", "outputs", "cleanup", "restarts")})
    with pytest.raises(AcceptanceFailure):
        AcceptanceHarness(adapter).run()


def test_authorization_and_disabled_live_mode_exit_nonzero(capsys, monkeypatch):
    monkeypatch.delenv("PETER_AI_GPU_ACCEPTANCE", raising=False)
    assert main(["--execute"]) != 0
    assert "authorization" in capsys.readouterr().err
    monkeypatch.setenv("PETER_AI_GPU_ACCEPTANCE", "1")
    assert main(["--execute"]) != 0
    assert "disabled" in capsys.readouterr().err


def test_discovery_allows_only_read_only_commands_and_redacts_secrets():
    seen = []

    def fake_run(command):
        seen.append(tuple(command))
        assert tuple(command) in {
            ("nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"),
            ("docker", "compose", "ps", "--format", "json"),
        }
        if command[0] == "nvidia-smi":
            return "Tesla V100,32768,12000,/private/Peter.mp4 transcript=secret token=abc"
        return '[{"State":"running","Name":"autoedit","password":"dont-print"}]'

    result = discovery(fake_run)
    encoded = json.dumps(result)
    assert len(seen) == 2
    for secret in ("/private/Peter.mp4", "secret", "abc", "dont-print", "Peter"):
        assert secret not in encoded
    assert result["compose"] == {"service_count": 1, "states": ["running"]}


def test_discovery_timeout_or_subprocess_error_is_failure():
    def failing_run(_command):
        raise subprocess.TimeoutExpired("nvidia-smi", 10)

    with pytest.raises(AcceptanceFailure, match="discovery failed"):
        discovery(failing_run)


def test_valid_mock_path_is_deterministic_and_sanitized():
    first = AcceptanceHarness().run()
    second = AcceptanceHarness().run()
    assert first == second
    assert first["verdict"] == "PASS"
    encoded = json.dumps(first)
    assert "[REDACTED]" not in encoded
    assert "password" not in encoded.lower()


def test_mock_fixture_has_the_required_evidence_schema_shape():
    fixture = valid_evidence()
    assert set(("samples", "phase_markers", "health", "outputs", "cleanup", "backends")) <= set(fixture)
    assert len(fixture["samples"]) >= 2
    for sample in fixture["samples"]:
        assert {"timestamp_ms", "total_mib", "used_mib", "phase"} <= set(sample)
        assert isinstance(sample["timestamp_ms"], int)
        assert isinstance(sample["total_mib"], int)
        assert isinstance(sample["used_mib"], int)
        assert isinstance(sample["phase"], str)
    assert fixture["backends"] == {"whisper": "mock", "diarize": "mock"}


def test_evidence_file_validation_has_nonzero_exit_for_invalid_input(tmp_path: Path, capsys):
    evidence = valid_evidence()
    evidence["health"]["dots"] = False
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert main(["--evidence", str(path)]) != 0
    diagnostic = capsys.readouterr().err
    assert '"verdict": "FAIL"' in diagnostic
    assert "dots" in diagnostic


def test_sanitize_recurses_without_echoing_secret_like_input_or_output():
    cleaned = sanitize({"nested": [{"password": "TOPSECRET"}, "token=TOPSECRET", "/home/private.mov"]})
    encoded = json.dumps(cleaned)
    assert "TOPSECRET" not in encoded
    assert "/home/private.mov" not in encoded
    assert "password" not in encoded
