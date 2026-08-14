from __future__ import annotations

import copy
import json

import pytest

from autoedit.ops.gate4_observer import (
    Gate4ObservationError,
    authenticate_observations,
    evaluate_gate4_observations,
)


OBSERVATION_KEY = b"external-observer-key-not-stored-in-evidence"
PHASES = (
    ("baseline", 10_000),
    ("dots_resident", 10_000),
    ("whisper_cold", 10_000),
    ("co_resident_idle", 1_000),
    ("active_overlap_1", 10_000),
    ("active_overlap_2", 10_000),
    ("post_workload", 30_000),
    ("cleanup_verify", 1_000),
)


def _compose():
    return {
        "services": {
            "app": {
                "network_mode": "host",
                "environment": {
                    "WHISPER_BACKEND": "mock",
                    "DIARIZE_BACKEND": "mock",
                    "WHISPERX_BASE_URL": "http://127.0.0.1:8011",
                },
            },
            "whisperx": {
                "ports": [{"host_ip": "127.0.0.1", "published": "8011", "target": 8011}],
                "volumes": [
                    {"source": "media", "target": "/data", "read_only": True},
                    {"source": "models", "target": "/models", "read_only": False},
                ],
                "healthcheck": {"test": ["CMD", "python3", "-c", "ready"]},
                "environment": {"WHISPERX_MAX_CONCURRENT_JOBS": "1"},
            },
        }
    }


def _events():
    events = []
    sequence = 0
    cursor = 0
    for phase, duration in PHASES:
        events.append({
            "sequence": sequence,
            "type": "phase",
            "phase": phase,
            "start_ms": cursor,
            "end_ms": cursor + duration,
        })
        sequence += 1
        for timestamp in range(cursor, cursor + duration + 1, 250):
            used = 8044 if phase in {"baseline", "cleanup_verify"} else 15_592
            events.append({
                "sequence": sequence,
                "type": "gpu_sample",
                "phase": phase,
                "timestamp_ms": timestamp,
                "total_mib": 32_768,
                "used_mib": used,
                "process_used_mib": [used],
                "unknown_processes": False,
            })
            sequence += 1
        events.append({
            "sequence": sequence,
            "type": "service_boundary",
            "phase": phase,
            "app_healthy": True,
            "dots_healthy": True,
            "worker_ready": phase not in {"baseline", "dots_resident"},
            "restart_delta": 0,
            "ollama_loaded_models": 0,
            "incident_codes": [],
        })
        sequence += 1
        cursor += duration + 250

    for phase in ("whisper_cold", "active_overlap_1", "active_overlap_2"):
        events.append({
            "sequence": sequence,
            "type": "whisper_output",
            "phase": phase,
            "job_state": "done",
            "input_hash_match": True,
            "aligned_word_count": 3,
            "speaker_count": 2,
        })
        sequence += 1
    for phase in ("active_overlap_1", "active_overlap_2"):
        events.append({
            "sequence": sequence,
            "type": "dots_output",
            "phase": phase,
            "api_status": "completed",
            "submitted_after_mtime_ns": 100,
            "output_mtime_ns": 200,
            "stable_mtime_observations": 2,
            "nonempty_bytes": 1024,
            "playable": True,
        })
        sequence += 1
        events.append({
            "sequence": sequence,
            "type": "overlap",
            "phase": phase,
            "dots_start_ms": 1_000,
            "dots_end_ms": 8_000,
            "whisper_start_ms": 2_000,
            "whisper_end_ms": 9_000,
        })
        sequence += 1
    events.append({
        "sequence": sequence,
        "type": "cleanup",
        "baseline_idle_mib": 8044,
        "post_cleanup_idle_mib": 8044,
        "app_healthy": True,
        "whisper_backend": "mock",
        "diarize_backend": "mock",
        "prior_artifact_unchanged": True,
        "prior_cut_unchanged": True,
    })
    return events


def _metadata():
    return {
        "source_commit": "a" * 40,
        "worker_image_digest": "sha256:" + "b" * 64,
        "compose_render_sha256": "sha256:" + "c" * 64,
        "authorization_ref": "decision-opaque-1",
        "fixture_ref": "fixture-opaque-1",
    }


def _signed(events=None, *, compose=None, metadata=None):
    compose = _compose() if compose is None else compose
    metadata = _metadata() if metadata is None else metadata
    return authenticate_observations(
        _events() if events is None else events,
        OBSERVATION_KEY,
        compose=compose,
        metadata=metadata,
    )


def _evaluate(compose=None, events=None, metadata=None):
    compose = _compose() if compose is None else compose
    metadata = _metadata() if metadata is None else metadata
    return evaluate_gate4_observations(
        compose,
        _signed(compose=compose, metadata=metadata) if events is None else events,
        metadata,
        observation_key=OBSERVATION_KEY,
    )


def test_observer_derives_pass_from_compose_and_complete_observations():
    result = _evaluate()
    assert result["verdict"] == "PASS"
    assert result["acceptance_source"] == "authenticated_observed_boundaries"
    assert result["workloads"] == {"whisper": 3, "dots": 2, "overlaps": 2}
    assert result["vram"]["peak_used_mib"] == 15_592
    assert result["vram"]["minimum_free_mib"] == 17_176


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda compose, events, metadata: events[0].__setitem__("verdict", "PASS"), "unknown field"),
        (lambda compose, events, metadata: events.pop(next(i for i, event in enumerate(events) if event.get("phase") == "active_overlap_2" and event["type"] == "phase")), "phase"),
        (lambda compose, events, metadata: compose["services"]["whisperx"].__setitem__("ports", ["0.0.0.0:8011:8011"]), "loopback"),
        (lambda compose, events, metadata: next(event for event in events if event["type"] == "dots_output").__setitem__("output_mtime_ns", 100), "mtime"),
        (lambda compose, events, metadata: next(event for event in events if event["type"] == "service_boundary").__setitem__("ollama_loaded_models", 1), "Ollama"),
        (lambda compose, events, metadata: next(event for event in events if event["type"] == "gpu_sample").__setitem__("unknown_processes", True), "unknown GPU"),
        (lambda compose, events, metadata: metadata.__setitem__("acceptance_pass", True), "unknown metadata"),
    ],
)
def test_observer_rejects_synthetic_or_incomplete_evidence(mutate, needle):
    compose, events, metadata = _compose(), _events(), _metadata()
    mutate(compose, events, metadata)
    with pytest.raises(Gate4ObservationError, match=needle):
        _evaluate(
            compose,
            authenticate_observations(
                events, OBSERVATION_KEY, compose=compose, metadata=metadata
            ),
            metadata,
        )


def test_observer_rejects_sampler_gap_over_500ms():
    events = _events()
    samples = [event for event in events if event["type"] == "gpu_sample"]
    samples[1]["timestamp_ms"] = samples[0]["timestamp_ms"] + 501
    with pytest.raises(Gate4ObservationError, match="gap"):
        _evaluate(events=_signed(events))


def test_hand_edited_observation_fails_external_authentication():
    events = _signed()
    events[-1]["app_healthy"] = False
    with pytest.raises(Gate4ObservationError, match="authentication"):
        _evaluate(events=events)


@pytest.mark.parametrize("target", ["compose", "metadata"])
def test_hand_edited_candidate_context_fails_external_authentication(target):
    compose, metadata = _compose(), _metadata()
    events = _signed(compose=compose, metadata=metadata)
    if target == "compose":
        compose["services"]["whisperx"]["environment"]["WHISPERX_MAX_CONCURRENT_JOBS"] = "2"
    else:
        metadata["fixture_ref"] = "different-fixture"
    with pytest.raises(Gate4ObservationError, match="authentication"):
        evaluate_gate4_observations(
            compose, events, metadata, observation_key=OBSERVATION_KEY
        )


def test_input_is_not_mutated():
    compose, events, metadata = _compose(), _signed(), _metadata()
    before = copy.deepcopy((compose, events, metadata))
    _evaluate(compose, events, metadata)
    assert (compose, events, metadata) == before


def test_file_only_cli_validates_signed_bundle(tmp_path, monkeypatch, capsys):
    from scripts import gate4_observer as cli

    compose_path = tmp_path / "compose.json"
    events_path = tmp_path / "events.ndjson"
    metadata_path = tmp_path / "metadata.json"
    compose_path.write_text(json.dumps(_compose()))
    events_path.write_text("".join(json.dumps(event) + "\n" for event in _signed()))
    metadata_path.write_text(json.dumps(_metadata()))
    monkeypatch.setenv("GATE4_OBSERVATION_KEY_HEX", OBSERVATION_KEY.hex())

    code = cli.main([
        "--compose-json", str(compose_path),
        "--events-ndjson", str(events_path),
        "--metadata-json", str(metadata_path),
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "PASS"


def test_worker_manager_rejects_parallel_gpu_execution():
    from services.whisperx_service.jobs import GPUJobManager

    with pytest.raises(ValueError, match="exactly one"):
        GPUJobManager(lambda _request: {}, max_workers=2)
