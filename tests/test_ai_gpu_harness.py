"""Offline acceptance coverage for the canonical AI-GPU-1 harness.

These tests use only in-memory evidence, fake clocks, and fake adapters. They
exercise the reviewed canonical contract (docs/plans/ai-gpu-1-redacted-evidence.
schema.json v1.0.0) and every fail-closed branch required by the runbook,
including the four compliance gaps closed by this correction:

* BUG-AIGPU1-001 candidate binding (exact source commit / image digest / render
  digest are required for a live pass).
* BUG-AIGPU1-002 discovery must never leak private paths, names, transcript
  text, runtime IDs, or secrets.
* BUG-AIGPU1-003 the harness evidence schema must reference / be semantically
  identical to the canonical plan schema.
* BUG-AIGPU1-004 the CLI must have explicit plan/validate/discover/mock/execute
  modes and emit the required exit classes (0/2/3/4/5/6/7), never a blanket 1.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from scripts.ai_gpu_acceptance import (
    EXIT_CLEANUP_ROLLBACK_FAILURE,
    EXIT_SUCCESS,
    EXIT_UNAUTHORIZED,
    EXIT_VALIDATION_FAILURE,
    AcceptanceFailure,
    MockAdapter,
    build_mock_evidence,
    discovery,
    mock_run,
    plan,
    sanitize,
    validate_evidence,
    validate_schema,
)


# ---------------------------------------------------------------------------
# Positive: a canonical mock instance validates and is not mistaken for live
# ---------------------------------------------------------------------------
def test_mock_evidence_is_canonical_and_schema_valid():
    evidence = build_mock_evidence()
    # Canonical top-level required fields are all present.
    for key in (
        "schema_version", "evidence_class", "run", "authorization", "redaction",
        "candidate", "project_context", "discovery", "compose", "measurement",
        "services", "workloads", "cleanup_and_rollback", "commands", "tests",
        "requirement_results", "overall",
    ):
        assert key in evidence, key
    assert evidence["schema_version"] == "1.0.0"
    assert evidence["evidence_class"] == "redacted_audit"


def test_mock_evidence_validates_against_canonical_schema():
    validate_schema(build_mock_evidence())  # raises on failure


def test_mock_run_passes_but_is_not_acceptance_eligible():
    result = mock_run()
    assert result["verdict"] == "PASS"
    assert result["acceptance_eligible"] is False
    assert result["acceptance_pass"] is False
    assert result["mode"] == "mock"


def test_valid_evidence_records_exact_candidate_binding_BUG_AIGPU1_001():
    evidence = build_mock_evidence()
    cand = evidence["candidate"]
    assert cand["source_commit"]
    assert cand["worker_image_digest"].startswith("sha256:")
    assert cand["compose_redacted_render_digest"].startswith("sha256:")
    assert evidence["tests"]["exact_candidate"] is True


def test_live_pass_requires_exact_candidate_binding_BUG_AIGPU1_001():
    evidence = build_mock_evidence()
    evidence["run"]["mode"] = "live"
    evidence["run"]["acceptance_eligible"] = True
    evidence["run"]["exit"] = {"code": 0, "class": "success"}
    evidence["authorization"]["status"] = "pass"
    evidence["authorization"]["explicit_peter_authorization"] = True
    evidence["authorization"]["decision_ref"] = "dec-peter-1"
    evidence["overall"]["status"] = "pass"
    evidence["overall"]["acceptance_pass"] = True
    # Drop the immutable candidate identifiers -> must fail closed.
    evidence["candidate"]["source_commit"] = None
    with pytest.raises(AcceptanceFailure, match="candidate"):
        validate_evidence(evidence)


# ---------------------------------------------------------------------------
# Negative: every required invalid condition exits the right class
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mutate,needle", [
    (lambda e: e["measurement"]["configuration"].__setitem__("nominal_interval_ms", 251), "1..250"),
    (lambda e: e["measurement"]["vram_summary"].__setitem__("minimum_free_mib", 1), "VRAM"),
    (lambda e: e["services"]["incidents"].__setitem__("oom", True), "incident"),
    (lambda e: e["services"].__setitem__("restart_delta_zero", False), "restart delta"),
    (lambda e: e["services"].__setitem__("ollama_unloaded_all_phases", False), "Ollama"),
    (lambda e: e["workloads"]["overlaps"][0].__setitem__("overlap_ms", 1000), "overlap"),
    (lambda e: e["workloads"]["whisper_outputs"][0].__setitem__("job_done", False), "Whisper"),
    (lambda e: e["workloads"]["dots_outputs"][0].__setitem__("nonempty_bytes", 0), "Dots"),
    (lambda e: e["measurement"]["phases"]["baseline"].__setitem__("duration_ms", 999), "baseline"),
    (lambda e: e["measurement"]["phases"]["post_workload"].__setitem__("duration_ms", 999), "post_workload"),
    (lambda e: e["measurement"]["phases"].pop("whisper_cold"), "missing phase"),
    (lambda e: e["measurement"]["samples"][0]["processes"][0].__setitem__("attribution_status", "unknown"),
        "unknown/unapproved"),
])
def test_semantic_invalid_conditions_fail_closed(mutate, needle):
    evidence = build_mock_evidence()
    mutate(evidence)
    with pytest.raises(AcceptanceFailure, match=needle):
        validate_evidence(evidence)


def test_cleanup_drift_fails_with_rollback_exit_class_BUG_AIGPU1_004():
    evidence = build_mock_evidence()
    evidence["cleanup_and_rollback"]["adjusted_drift_mib"] = 513
    with pytest.raises(AcceptanceFailure) as exc:
        validate_evidence(evidence)
    assert exc.value.exit_class == EXIT_CLEANUP_ROLLBACK_FAILURE


def test_unapproved_cleanup_mutation_fails_rollback():
    evidence = build_mock_evidence()
    evidence["cleanup_and_rollback"]["unapproved_resource_mutation_attempted"] = True
    with pytest.raises(AcceptanceFailure) as exc:
        validate_evidence(evidence)
    assert exc.value.exit_class == EXIT_CLEANUP_ROLLBACK_FAILURE


def test_raw_sensitive_payload_fails_redaction_exit_class():
    evidence = build_mock_evidence()
    evidence["redaction"]["raw_sensitive_payloads_present"] = True
    with pytest.raises(AcceptanceFailure) as exc:
        validate_evidence(evidence)
    assert exc.value.exit_class == 6  # redaction_failure


def test_schema_violation_fails_validation_exit_class():
    evidence = build_mock_evidence()
    evidence["schema_version"] = "9.9.9"  # const violation
    with pytest.raises(AcceptanceFailure) as exc:
        validate_evidence(evidence)
    assert exc.value.exit_class == EXIT_VALIDATION_FAILURE


# ---------------------------------------------------------------------------
# CLI / mode contract (BUG-AIGPU1-004): explicit modes, correct exit classes
# ---------------------------------------------------------------------------
def test_plan_mode_validates_canonical_schema_and_exits_zero():
    assert plan()["verdict"] == "PASS"
    # plan proves the harness can build a canonical instance.
    assert validate_schema(build_mock_evidence()) is None


def test_no_args_or_unknown_mode_is_usage_error():
    import scripts.ai_gpu_acceptance as m
    # argparse's required-group failure raises SystemExit(2); the CLI must not
    # silently default to a mock pass.
    for argv in ([], ["--bogus"]):
        with pytest.raises(SystemExit) as exc:
            m.main(argv)
        assert exc.value.code == EXIT_VALIDATION_FAILURE


def test_mock_cli_exits_zero_and_records_not_eligible():
    import scripts.ai_gpu_acceptance as m
    assert m.main(["--mock"]) == EXIT_SUCCESS


def test_execute_without_authorization_exits_unauthorized():
    import scripts.ai_gpu_acceptance as m
    assert m.main(["--execute"]) == EXIT_UNAUTHORIZED


def test_discovery_cli_redacts_private_data_and_exits_zero(monkeypatch, capsys):
    import scripts.ai_gpu_acceptance as m

    class FakeAdapter(MockAdapter):
        def run_read_only(self, command, timeout_s=10):
            if command[0] == "nvidia-smi":
                return "/private/Peter.mp4 transcript=secret token=abc runtime-id-99"
            return '[{"State":"running","Name":"autoedit","password":"dont-print"}]'

    assert m.main(["--discover"], adapter=FakeAdapter()) == EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "/private/Peter.mp4" not in out
    assert "secret" not in out
    assert "abc" not in out
    assert "dont-print" not in out
    assert "Peter" not in out


# ---------------------------------------------------------------------------
# Discovery privacy (BUG-AIGPU1-002): bounded allowlist, no private leakage
# ---------------------------------------------------------------------------
def test_discovery_allowlist_only_issues_approved_commands():
    class AllowlistProbe(MockAdapter):
        def __init__(self):
            super().__init__()
            self.seen = []

        def run_read_only(self, command, timeout_s=10):
            self.seen.append(tuple(command))
            if command[0] == "nvidia-smi":
                return "Tesla-V100,32768,12000"
            return '[{"State":"running","Name":"autoedit"}]'

    adp = AllowlistProbe()
    result = discovery(adp)
    assert len(adp.seen) == 2
    assert result["mode"] == "discovery"
    assert result["read_only"] is True


def test_discovery_redacts_private_paths_names_transcript_runtime_ids_secrets():
    class HostileAdapter(MockAdapter):
        def run_read_only(self, command, timeout_s=10):
            if command[0] == "nvidia-smi":
                return "/private/media/angle.mp4,Alice transcript=hello-world runtime-id-99 token=TOKEN123"
            return '[{"Name":"autoedit","State":"running","cookie":"sess-xyz"}]'

    result = discovery(HostileAdapter())
    encoded = json.dumps(result, sort_keys=True)
    for bad in ("/private/media/angle.mp4", "Alice", "transcript=hello-world",
                "runtime-id-99", "TOKEN123", "sess-xyz"):
        assert bad not in encoded


def test_discovery_timeout_or_subprocess_error_is_unavailable():
    class FailingAdapter(MockAdapter):
        def run_read_only(self, command, timeout_s=10):
            raise subprocess.TimeoutExpired("nvidia-smi", 10)

    with pytest.raises(AcceptanceFailure) as exc:
        discovery(FailingAdapter())
    assert exc.value.exit_class == 3  # unavailable


def test_sanitize_drops_secret_keys_and_redacts_values():
    payload = {
        "password": "TOPSECRET",
        "note": "/home/peter/secret-clip.mov",
        "id": "proc-id-77=abc",
        "text": "transcript=ConfidentialName",
        "nested": {"token": "X"},
    }
    cleaned = sanitize(payload)
    encoded = json.dumps(cleaned, sort_keys=True)
    assert "TOPSECRET" not in encoded
    assert "/home/peter/secret-clip.mov" not in encoded
    assert "proc-id-77" not in encoded
    assert "ConfidentialName" not in encoded
    assert "password" not in encoded
    assert "token" not in encoded


# ---------------------------------------------------------------------------
# Evidence schema references canonical contract (BUG-AIGPU1-003)
# ---------------------------------------------------------------------------
def test_harness_schema_file_references_canonical_contract():
    import scripts.ai_gpu_acceptance as m
    schema_path = m.HARNESS_SCHEMA_PATH
    assert schema_path.exists()
    harness_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # The Programmer-owned schema references the canonical plan schema, proving
    # semantic identity rather than carrying a divergent permissive contract.
    assert harness_schema.get("$ref") == "../docs/plans/ai-gpu-1-redacted-evidence.schema.json"
    canonical = json.loads(m.CANONICAL_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert canonical["$id"].endswith("ai-gpu-1-redacted-evidence-1.0.0.json")
    assert canonical["additionalProperties"] is False


def test_evidence_file_validation_has_nonzero_exit_for_invalid_input(tmp_path, capsys):
    import scripts.ai_gpu_acceptance as m

    evidence = build_mock_evidence()
    evidence["measurement"]["vram_summary"]["minimum_free_mib"] = 1
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert m.main(["--validate", str(path)]) == EXIT_VALIDATION_FAILURE
    diagnostic = capsys.readouterr().err
    assert "VRAM" in diagnostic
