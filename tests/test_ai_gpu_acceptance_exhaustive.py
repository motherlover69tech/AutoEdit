"""Exhaustive offline acceptance coverage for every AI-GPU-1 fail-closed branch.

These tests intentionally use only in-memory evidence, fake clocks, and fake
adapters.  A real host, network, Docker, GPU, Dots, Ollama, or Unraid must
never be needed to collect this module.

It asserts the canonical contract: schema validity, every semantic rule, the
required exit classes (0/2/3/4/5/6/7), privacy redaction, and that a mock run
never reports acceptance_eligible/acceptance_pass.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from scripts.ai_gpu_acceptance import (
    EXIT_ADAPTER_ERROR,
    EXIT_CLEANUP_ROLLBACK_FAILURE,
    EXIT_SUCCESS,
    EXIT_UNAUTHORIZED,
    EXIT_VALIDATION_FAILURE,
    AcceptanceFailure,
    MockAdapter,
    build_mock_evidence,
    discovery,
    main,
    mock_run,
    sanitize,
    validate_evidence,
    validate_schema,
)


def valid_evidence() -> dict:
    return build_mock_evidence()


def expect_failure(mutator, message: str, *, exit_class: int | None = None) -> None:
    evidence = valid_evidence()
    mutator(evidence)
    with pytest.raises(AcceptanceFailure, match=message) as exc:
        validate_evidence(evidence)
    if exit_class is not None:
        assert exc.value.exit_class == exit_class


# ---------------------------------------------------------------------------
# Sampler / clock / phase / process accounting
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mutate,message", [
    (lambda e: e["measurement"]["configuration"].__setitem__("nominal_interval_ms", 251), "1..250"),
    (lambda e: _break_gap(e), "gap"),
    (lambda e: _break_monotonic(e), "not increasing"),
    (lambda e: e["measurement"]["samples"].__setitem__(0, {**e["measurement"]["samples"][0], "used_mib": 99999}), "reconcile"),
    (lambda e: e["measurement"]["samples"][0]["processes"][0].__setitem__("pid", 0), "per-process"),
    (lambda e: e["measurement"]["samples"][0]["processes"][0].__setitem__("attribution_status", "unknown"), "unknown/unapproved"),
])
def test_sampler_and_clock_and_process_fail_closed(mutate, message):
    expect_failure(mutate, message)


def _break_gap(e):
    s = e["measurement"]["samples"][5]
    e["measurement"]["samples"][5] = {**s, "observed_monotonic_ns": s["observed_monotonic_ns"] + 600_000_000}


def _break_monotonic(e):
    prev = e["measurement"]["samples"][4]
    e["measurement"]["samples"][5] = {**e["measurement"]["samples"][5],
                                      "observed_monotonic_ns": prev["observed_monotonic_ns"] - 1}


def test_irreconcilable_wall_and_monotonic_clocks_fail():
    evidence = valid_evidence()
    # Make a wall timestamp diverge far from its monotonic anchor.
    bad = dict(evidence["measurement"]["samples"][3])
    bad["wall_utc"] = "2023-11-14T22:13:20.000000000Z"
    evidence["measurement"]["samples"][3] = bad
    with pytest.raises(AcceptanceFailure, match="reconciliation"):
        validate_evidence(evidence)


@pytest.mark.parametrize("mutate,message", [
    (lambda e: e["measurement"]["phases"].pop("whisper_cold"), "missing phase"),
    (lambda e: e["measurement"]["phases"]["baseline"].__setitem__("sequence", 3), "out of sequence"),
    (lambda e: e["measurement"]["phases"]["baseline"].__setitem__("duration_ms", 999), "baseline"),
    (lambda e: e["measurement"]["phases"]["dots_resident"].__setitem__("duration_ms", 999), "dots_resident"),
    (lambda e: e["measurement"]["phases"]["post_workload"].__setitem__("duration_ms", 999), "post_workload"),
])
def test_phase_markers_fail_closed(mutate, message):
    expect_failure(mutate, message)


def test_missing_required_evidence_field_fails_schema():
    for key in (
        "schema_version", "evidence_class", "run", "authorization", "redaction",
        "candidate", "project_context", "discovery", "compose", "measurement",
        "services", "workloads", "cleanup_and_rollback", "commands", "tests",
        "requirement_results", "overall",
    ):
        evidence = valid_evidence()
        evidence.pop(key)
        with pytest.raises(AcceptanceFailure):
            validate_evidence(evidence)


def test_malformed_evidence_json_fails_cli(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert main(["--validate", str(path)]) == EXIT_ADAPTER_ERROR
    assert "FAIL" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Health / output / overlap / VRAM / cleanup
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mutate,message", [
    (lambda e: e["services"]["incidents"].__setitem__("app_health_loss", True), "incident"),
    (lambda e: e["services"]["incidents"].__setitem__("oom", True), "incident"),
    (lambda e: e["services"].__setitem__("restart_delta_zero", False), "restart delta"),
    (lambda e: e["services"].__setitem__("ollama_unloaded_all_phases", False), "Ollama"),
    (lambda e: e["workloads"]["whisper_outputs"][0].__setitem__("job_done", False), "Whisper"),
    (lambda e: e["workloads"]["whisper_outputs"][0].__setitem__("input_hash_match", False), "Whisper"),
    (lambda e: e["workloads"]["whisper_outputs"][0].__setitem__("raw_payload_present", True), "Whisper"),
    (lambda e: e["workloads"]["dots_outputs"][0].__setitem__("nonempty_bytes", 0), "Dots"),
    (lambda e: e["workloads"]["dots_outputs"][0].__setitem__("raw_audio_present", True), "Dots"),
    (lambda e: e["workloads"]["overlaps"][0].__setitem__("overlap_ms", 1000), "overlap"),
    (lambda e: e["measurement"]["vram_summary"].__setitem__("minimum_free_mib", 1), "VRAM"),
    (lambda e: e["measurement"]["vram_summary"].__setitem__("unknown_process_count", 2), "peak"),
    (lambda e: e["cleanup_and_rollback"].__setitem__("adjusted_drift_mib", 513), "drift"),
    (lambda e: e["cleanup_and_rollback"].__setitem__("app_healthy_after_cleanup", False), "app not healthy"),
    (lambda e: e["cleanup_and_rollback"].__setitem__(
        "production_backends_after_cleanup", {"whisper": "real", "diarize": "mock"}), "mock"),
])
def test_health_output_overlap_vram_cleanup_fail_closed(mutate, message):
    expect_failure(mutate, message)


def test_cleanup_drift_uses_rollback_exit_class():
    expect_failure(
        lambda e: e["cleanup_and_rollback"].__setitem__("adjusted_drift_mib", 600),
        "drift", exit_class=EXIT_CLEANUP_ROLLBACK_FAILURE,
    )


def test_unapproved_cleanup_mutation_uses_rollback_exit_class():
    expect_failure(
        lambda e: e["cleanup_and_rollback"].__setitem__("unapproved_resource_mutation_attempted", True),
        "unapproved", exit_class=EXIT_CLEANUP_ROLLBACK_FAILURE,
    )


# ---------------------------------------------------------------------------
# Authorization / discovery / execute modes
# ---------------------------------------------------------------------------
def test_authorization_missing_blocks_execute():
    assert main(["--execute"]) == EXIT_UNAUTHORIZED


def test_execute_never_runs_without_full_authorization():
    class LiveLikeAdapter(MockAdapter):
        def submit_workload(self, kind):
            raise AcceptanceFailure("no live adapter", exit_class=EXIT_UNAUTHORIZED)

    assert main(["--execute"], adapter=LiveLikeAdapter()) == EXIT_UNAUTHORIZED


def test_discovery_allows_only_read_only_commands_and_redacts_secrets():
    seen = []

    class Probe(MockAdapter):
        def run_read_only(self, command, timeout_s=10):
            seen.append(tuple(command))
            assert tuple(command) in {
                ("nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"),
                ("docker", "compose", "ps", "--format", "json"),
            }
            if command[0] == "nvidia-smi":
                return "Tesla V100,32768,12000,/private/Peter.mp4 transcript=secret token=abc"
            return '[{"State":"running","Name":"autoedit","password":"dont-print"}]'

    result = discovery(Probe())
    encoded = json.dumps(result)
    assert len(seen) == 2
    for secret in ("/private/Peter.mp4", "secret", "abc", "dont-print", "Peter"):
        assert secret not in encoded
    assert result["compose"] == {"service_count": 1, "states": ["running"]}


def test_discovery_timeout_is_unavailable():
    class Failing(MockAdapter):
        def run_read_only(self, command, timeout_s=10):
            raise subprocess.TimeoutExpired("nvidia-smi", 10)

    with pytest.raises(AcceptanceFailure) as exc:
        discovery(Failing())
    assert exc.value.exit_class == 3  # unavailable
    assert main(["--discover"], adapter=Failing()) == 3


def test_discovery_allowlists_single_token_host_labels():
    """Host labels must not become durable evidence when not name-like."""
    class Hostile(MockAdapter):
        def run_read_only(self, command, timeout_s=10):
            if command[0] == "nvidia-smi":
                return "Alice,32768,12000"
            return '[{"State":"Alice","Name":"Alice"}]'

    result = discovery(Hostile())
    assert result["gpu"]["model"] == "unknown"
    assert result["compose"]["states"] == ["unknown"]
    assert "Alice" not in json.dumps(result)


def test_local_readonly_discovery_fails_unavailable_when_tool_absent():
    # The CLI default adapter shells out to the allowlisted read-only commands
    # and must fail closed (unavailable) when the host tooling is absent, never
    # faking a pass or mutating anything.
    import shutil
    if shutil.which("nvidia-smi") is None:
        assert main(["--discover"]) == 3
    else:  # pragma: no cover - not present on this CI host
        assert main(["--discover"]) == EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Mock determinism / schema identity / redaction
# ---------------------------------------------------------------------------
def test_mock_fixture_is_deterministic_canonical_and_not_acceptance():
    first = mock_run()
    second = mock_run()
    assert first == second
    assert first["verdict"] == "PASS"
    encoded = json.dumps(first)
    assert "[REDACTED]" not in encoded
    # Mock is never live acceptance.
    assert first["acceptance_eligible"] is False
    assert first["acceptance_pass"] is False


def test_mock_evidence_conforms_to_canonical_schema():
    validate_schema(valid_evidence())


def test_sanitize_recurses_without_echoing_secret_like_input_or_output():
    cleaned = sanitize({"nested": [{"password": "TOPSECRET"}, "token=TOPSECRET", "/home/private.mov"]})
    encoded = json.dumps(cleaned)
    assert "TOPSECRET" not in encoded
    assert "/home/private.mov" not in encoded
    assert "password" not in encoded


def test_evidence_file_validation_has_nonzero_exit_for_invalid_input(tmp_path, capsys):
    evidence = valid_evidence()
    evidence["measurement"]["vram_summary"]["minimum_free_mib"] = 1
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert main(["--validate", str(path)]) == EXIT_VALIDATION_FAILURE
    diagnostic = capsys.readouterr().err
    assert "VRAM" in diagnostic
    assert "exit_class" in diagnostic


def test_valid_mock_cli_path_exits_zero():
    assert main(["--mock"]) == EXIT_SUCCESS


def test_plan_cli_proves_canonical_schema_and_exits_zero():
    assert main(["--plan"]) == EXIT_SUCCESS


def test_discovery_cli_exits_zero_when_tooling_present():
    class Present(MockAdapter):
        def run_read_only(self, command, timeout_s=10):
            if command[0] == "nvidia-smi":
                return "Tesla-V100,32768,12000"
            return '[{"State":"running","Name":"autoedit"}]'

    assert main(["--discover"], adapter=Present()) == EXIT_SUCCESS
