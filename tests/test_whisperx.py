from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine

from services.whisperx_service.jobs import GPUJobQueueFull

from autoedit.api import create_app
from autoedit.config import Settings
from autoedit.transcribe import (
    WhisperXClient,
    normalize_whisperx_result,
    resolve_shared_audio_path,
)

_SERVICE_PATH = (
    Path(__file__).parents[1] / "services" / "whisperx_service" / "app.py"
)
_SERVICE_SPEC = importlib.util.spec_from_file_location(
    "autoedit_test_whisperx_service", _SERVICE_PATH
)
assert _SERVICE_SPEC is not None and _SERVICE_SPEC.loader is not None
_SERVICE_MODULE = importlib.util.module_from_spec(_SERVICE_SPEC)
sys.modules[_SERVICE_SPEC.name] = _SERVICE_MODULE
_SERVICE_SPEC.loader.exec_module(_SERVICE_MODULE)
whisperx_app = _SERVICE_MODULE.app


def _settings(**overrides) -> Settings:
    values = {
        "WHISPER_BACKEND": "whisperx",
        "WHISPER_MODEL": "large-v3",
        "WHISPERX_BASE_URL": "http://whisperx.test:8011",
        "WHISPER_LANGUAGE": "en",
        "WHISPER_BATCH_SIZE": 4,
        "WHISPER_COMPUTE_TYPE": "float16",
        "WHISPER_ALIGN": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_normalize_whisperx_result_applies_offset_once_to_segments_and_words():
    payload = {
        "language": "en",
        "segments": [
            {
                "start": 1.25,
                "end": 2.5,
                "text": " Hello world ",
                "words": [
                    {"word": "Hello", "start": 1.25, "end": 1.7, "score": 0.97},
                    {"word": "world", "start": 1.75, "end": 2.5, "score": 0.91},
                ],
            }
        ],
    }

    result = normalize_whisperx_result(payload, start_ms=50, speaker_label="guest")

    assert result == {
        "language": "en",
        "segments": [
            {
                "speaker": "guest",
                "start_ms": 1300,
                "end_ms": 2550,
                "text": "Hello world",
                "words": [
                    {"w": "Hello", "start_ms": 1300, "end_ms": 1750, "conf": 0.97},
                    {"w": "world", "start_ms": 1800, "end_ms": 2550, "conf": 0.91},
                ],
            }
        ],
    }


def test_normalize_whisperx_result_keeps_unaligned_words_without_fake_timestamps():
    payload = {
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "£13.60",
                "words": [{"word": "£13.60", "score": 0.72}],
            }
        ]
    }

    result = normalize_whisperx_result(payload, start_ms=0, speaker_label="host")

    assert result["segments"][0]["words"] == [{"w": "£13.60", "conf": 0.72}]


def test_normalize_whisperx_result_discards_preroll_and_clips_master_zero():
    payload = {
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "before"},
            {
                "start": 1.0,
                "end": 3.0,
                "text": "crosses zero",
                "words": [
                    {"word": "crosses", "start": 1.0, "end": 1.8},
                    {"word": "zero", "start": 2.1, "end": 3.0},
                ],
            },
        ]
    }

    result = normalize_whisperx_result(payload, start_ms=-2_000, speaker_label="host")

    assert result["segments"] == [
        {
            "speaker": "host",
            "start_ms": 0,
            "end_ms": 1_000,
            "text": "crosses zero",
            "words": [{"w": "zero", "start_ms": 100, "end_ms": 1_000}],
        }
    ]


def test_whisperx_client_sends_shared_path_and_configured_options(tmp_path: Path):
    wav = tmp_path / "speaker.wav"
    wav.write_bytes(b"RIFF")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={"language": "en", "segments": [{"start": 0, "end": 1, "text": "Hi"}]},
        )

    client = WhisperXClient(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    result = client.transcribe(wav)

    assert seen == {
        "audio_path": str(wav.resolve()),
        "model": "large-v3",
        "language": "en",
        "batch_size": 4,
        "compute_type": "float16",
        "align": True,
    }
    assert result["segments"][0]["text"] == "Hi"


def test_whisperx_client_reports_service_errors(tmp_path: Path):
    wav = tmp_path / "speaker.wav"
    wav.write_bytes(b"RIFF")

    client = WhisperXClient(
        _settings(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"detail": "model unavailable"})
        ),
    )

    with pytest.raises(RuntimeError, match="503.*model unavailable"):
        client.transcribe(wav)


def test_backend_selector_rejects_unknown_backend_during_settings_validation():
    with pytest.raises(ValidationError, match="WHISPER_BACKEND"):
        _settings(WHISPER_BACKEND="magic")


def test_application_rejects_unknown_backend_at_startup(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported WHISPER_BACKEND"):
        create_app(
            engine=create_engine("sqlite:///:memory:"),
            data_root=tmp_path,
            auth_enabled=False,
            whisper_backend="magic",
        )


def test_service_resolves_audio_inside_shared_data_root(tmp_path: Path):
    audio = tmp_path / "project" / "audio" / "speaker.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"RIFF")

    assert resolve_shared_audio_path(str(audio), tmp_path) == audio.resolve()
    assert resolve_shared_audio_path("project/audio/speaker.wav", tmp_path) == audio.resolve()


def test_service_rejects_paths_outside_shared_data_root(tmp_path: Path):
    outside = tmp_path.parent / "secret.wav"
    outside.write_bytes(b"RIFF")
    try:
        with pytest.raises(ValueError, match="inside DATA_ROOT"):
            resolve_shared_audio_path(str(outside), tmp_path)
        with pytest.raises(ValueError, match="inside DATA_ROOT"):
            resolve_shared_audio_path("../secret.wav", tmp_path)
    finally:
        outside.unlink()


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"segments": [-1]}, "must be an object"),
        ({"segments": [{"start": -1, "end": 1, "text": "bad"}]}, "non-negative"),
        ({"segments": [{"start": 0, "end": float("nan"), "text": "bad"}]}, "finite"),
        (
            {
                "segments": [
                    {
                        "start": 0,
                        "end": 1,
                        "text": "bad",
                        "words": ["not-an-object"],
                    }
                ]
            },
            "must be an object",
        ),
        (
            {
                "segments": [
                    {
                        "start": 0,
                        "end": 1,
                        "text": "bad",
                        "words": [{"word": "bad", "start": 0.5, "end": 1.5}],
                    }
                ]
            },
            "inside the segment",
        ),
        (
            {
                "segments": [
                    {
                        "start": 0,
                        "end": 1,
                        "text": "bad",
                        "words": [{"word": "bad", "score": 1.5}],
                    }
                ]
            },
            "between 0 and 1",
        ),
        ({"segments": [{"start": "0", "end": 1, "text": "bad"}]}, "number"),
        (
            {
                "segments": [
                    {
                        "start": 0,
                        "end": 1,
                        "text": "bad",
                        "words": [{"word": 123}],
                    }
                ]
            },
            "word must be a string",
        ),
        (
            {
                "segments": [
                    {
                        "start": 0,
                        "end": 1,
                        "text": "bad",
                        "words": [{"word": "bad", "score": True}],
                    }
                ]
            },
            "between 0 and 1",
        ),
    ],
)
def test_normalizer_rejects_malformed_authoritative_timeline_data(payload, message):
    with pytest.raises(ValueError, match=message):
        normalize_whisperx_result(payload, start_ms=0, speaker_label="host")


@pytest.mark.parametrize(
    "override",
    [
        {"WHISPER_BACKEND": "magic"},
        {"WHISPER_BATCH_SIZE": 0},
        {"WHISPERX_TIMEOUT_SECONDS": -1},
        {"WHISPERX_BASE_URL": "file:///tmp/worker"},
        {"WHISPER_COMPUTE_TYPE": "unknown"},
    ],
)
def test_whisper_settings_reject_invalid_values_at_construction(override):
    with pytest.raises(ValidationError):
        _settings(**override)


def test_worker_health_is_liveness_only_and_does_not_disclose_data_root():
    response = TestClient(whisperx_app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_worker_readiness_fails_closed_without_cuda_and_hides_details():
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        float16=object(),
    )
    with patch.dict(sys.modules, {"torch": fake_torch, "whisperx": object()}):
        response = TestClient(whisperx_app).get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "WhisperX worker is not ready"}


def test_worker_readiness_requires_configured_diarization_pipeline():
    class Probe:
        def __add__(self, other):
            return self

        def item(self):
            return 2.0

    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            get_device_capability=lambda: (7, 0),
        ),
        float16=object(),
        ones=lambda *args, **kwargs: Probe(),
    )
    with patch.dict(sys.modules, {"torch": fake_torch, "whisperx": object()}), patch.object(
        _SERVICE_MODULE, "DIARIZE_ENABLED", True
    ), patch.object(_SERVICE_MODULE, "_load_asr_model"), patch.object(
        _SERVICE_MODULE,
        "_load_diarization_pipeline",
        side_effect=RuntimeError("gated model unavailable"),
    ) as load_diarization:
        response = TestClient(whisperx_app).get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "WhisperX worker is not ready"}
    load_diarization.assert_called_once_with()


def test_worker_missing_audio_error_does_not_disclose_absolute_path(tmp_path: Path):
    missing = tmp_path / "private-project" / "secret.wav"
    with patch.object(_SERVICE_MODULE, "DATA_ROOT", str(tmp_path)):
        response = TestClient(whisperx_app).post(
            "/v1/transcribe",
            json={"audio_path": str(missing)},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "audio file not found"}
    assert str(tmp_path) not in response.text


def test_worker_analyze_rejects_hash_mismatch_before_queueing(tmp_path: Path):
    audio = tmp_path / "analysis.wav"
    audio.write_bytes(b"audio")
    client = TestClient(whisperx_app)
    with patch.object(_SERVICE_MODULE, "DATA_ROOT", str(tmp_path)):
        response = client.post(
            "/v1/analyze",
            json={
                "audio_path": str(audio),
                "input_sha256": "0" * 64,
                "model": "large-v3",
                "language": "en",
                "batch_size": 4,
                "compute_type": "float16",
                "align": True,
                "diarize": False,
            },
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "input_sha256 does not match audio input"}


def test_worker_analyze_rejects_diarization_when_server_disabled(tmp_path: Path):
    import hashlib

    audio = tmp_path / "analysis.wav"
    audio.write_bytes(b"audio")
    payload_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
    client = TestClient(whisperx_app)
    with patch.object(_SERVICE_MODULE, "DATA_ROOT", str(tmp_path)), patch.object(
        _SERVICE_MODULE, "DIARIZE_ENABLED", False
    ):
        response = client.post(
            "/v1/analyze",
            json={
                "audio_path": str(audio),
                "input_sha256": payload_hash,
                "model": "large-v3",
                "language": "en",
                "batch_size": 4,
                "compute_type": "float16",
                "align": True,
                "diarize": True,
            },
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "diarize must be False"}


def test_worker_analyze_rejects_invalid_speaker_bounds_before_queueing(tmp_path: Path):
    import hashlib

    audio = tmp_path / "analysis.wav"
    audio.write_bytes(b"audio")
    payload_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
    with patch.object(_SERVICE_MODULE, "DATA_ROOT", str(tmp_path)), patch.object(
        _SERVICE_MODULE, "DIARIZE_ENABLED", True
    ), patch.object(_SERVICE_MODULE._job_manager, "submit") as submit:
        response = TestClient(whisperx_app).post(
            "/v1/analyze",
            json={
                "audio_path": str(audio),
                "input_sha256": payload_hash,
                "diarize": True,
                "min_speakers": 3,
                "max_speakers": 2,
            },
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "min_speakers must not exceed max_speakers"}
    submit.assert_not_called()


def test_worker_analyze_returns_429_when_gpu_queue_is_full(tmp_path: Path):
    import hashlib

    audio = tmp_path / "analysis.wav"
    audio.write_bytes(b"audio")
    payload_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
    with patch.object(_SERVICE_MODULE, "DATA_ROOT", str(tmp_path)), patch.object(
        _SERVICE_MODULE._job_manager,
        "submit",
        side_effect=GPUJobQueueFull("WhisperX analysis queue is full"),
    ):
        response = TestClient(whisperx_app).post(
            "/v1/analyze",
            json={
                "audio_path": str(audio),
                "input_sha256": payload_hash,
            },
        )

    assert response.status_code == 429
    assert response.json() == {"detail": "WhisperX analysis queue is full"}


def test_worker_job_routes_hide_unknown_job_details():
    client = TestClient(whisperx_app)

    get_response = client.get("/v1/jobs/not-real")
    cancel_response = client.post("/v1/jobs/not-real/cancel")
    assert get_response.status_code == 404
    assert cancel_response.status_code == 404
    assert get_response.json() == {"detail": "job not found"}
    assert cancel_response.json() == {"detail": "job not found"}


def test_worker_loads_diarization_pipeline_from_versioned_submodule():
    seen = {}

    class FakeDiarizationPipeline:
        def __init__(self, model_name=None, token=None, device=None):
            seen.update(model_name=model_name, token=token, device=device)

    fake_diarize = SimpleNamespace(DiarizationPipeline=FakeDiarizationPipeline)
    _SERVICE_MODULE._load_diarization_pipeline.cache_clear()
    try:
        with patch.dict(
            sys.modules,
            {
                "whisperx": SimpleNamespace(),
                "whisperx.diarize": fake_diarize,
            },
        ), patch.dict("os.environ", {"HF_TOKEN": "test-token"}, clear=False):
            pipeline = _SERVICE_MODULE._load_diarization_pipeline()
    finally:
        _SERVICE_MODULE._load_diarization_pipeline.cache_clear()

    assert isinstance(pipeline, FakeDiarizationPipeline)
    assert seen == {
        "model_name": _SERVICE_MODULE.DIARIZATION_MODEL,
        "token": "test-token",
        "device": _SERVICE_MODULE.DEVICE,
    }


def test_normalize_diarization_turns_derives_overlap_and_preserves_input_order():
    turns = _SERVICE_MODULE._normalize_diarization_turns(
        [
            {"start": 2.0, "end": 2.5, "speaker": "SPEAKER_00"},
            {"start": 0.8, "end": 1.5, "speaker": "SPEAKER_01"},
            {"start": 0.1, "end": 1.2, "speaker": "SPEAKER_00"},
        ]
    )

    assert [turn["turn_id"] for turn in turns] == ["turn-1", "turn-2", "turn-3"]
    assert [turn["start"] for turn in turns] == [2.0, 0.8, 0.1]
    assert [turn["overlap"] for turn in turns] == [False, True, True]


def test_normalize_diarization_turns_overlap_edge_cases():
    turns = _SERVICE_MODULE._normalize_diarization_turns(
        [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
            {"start": 3.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 4.0, "end": 6.0, "speaker": "SPEAKER_00"},
            {"start": 7.0, "end": 8.0, "speaker": "SPEAKER_00", "overlap": True},
        ]
    )

    # Touching boundaries and same-speaker intersections are not cross-talk;
    # an explicit backend overlap marker remains authoritative.
    assert [turn["overlap"] for turn in turns] == [False, False, False, False, True]


@pytest.mark.parametrize(
    "row",
    [
        {"start": True, "end": 1.0, "speaker": "SPEAKER_00"},
        {"start": 0.0, "end": float("inf"), "speaker": "SPEAKER_00"},
        {"start": 1.0, "end": 1.0, "speaker": "SPEAKER_00"},
        {"start": 0.0, "end": 1.0, "speaker": ""},
        "not-an-object",
    ],
)
def test_normalize_diarization_turns_rejects_malformed_rows(row):
    with pytest.raises((TypeError, ValueError)):
        _SERVICE_MODULE._normalize_diarization_turns([row])


def test_normalize_diarization_turns_scales_for_concurrent_input():
    rows = [
        {"start": 0.0, "end": 10.0, "speaker": f"SPEAKER_{index % 2:02d}"}
        for index in range(4000)
    ]

    turns = _SERVICE_MODULE._normalize_diarization_turns(rows)

    assert len(turns) == 4000
    assert all(turn["overlap"] for turn in turns)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model", "arbitrary/model", "model must be"),
        ("compute_type", "int8", "compute_type must be"),
        ("batch_size", 5, "batch_size must not exceed"),
        ("language", "fr", "language must be"),
        ("align", False, "align must be"),
    ],
)
def test_worker_rejects_caller_selected_runtime_options_before_loading_runtime(
    field, value, message
):
    payload = {"audio_path": "/data/test.wav"}
    payload[field] = value
    response = TestClient(whisperx_app).post("/v1/transcribe", json=payload)

    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_worker_does_not_disclose_internal_exception_details():
    with patch.object(
        _SERVICE_MODULE,
        "run_whisperx",
        side_effect=RuntimeError("private path /data/project/interview.wav"),
    ):
        response = TestClient(whisperx_app).post(
            "/v1/transcribe",
            json={"audio_path": "/data/test.wav"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "WhisperX transcription failed"}


def test_gpu_overlay_keeps_worker_loopback_only_and_reachable_from_host_networked_app():
    repo = Path(__file__).parents[1]
    base = (repo / "docker-compose.yml").read_text()
    overlay = (repo / "docker-compose.gpu-ai.yml").read_text()

    assert "network_mode: host" in base
    assert "WHISPERX_BASE_URL: http://127.0.0.1:8011" in overlay
    assert '127.0.0.1:8011:8011' in overlay
    assert "WHISPERX_BASE_URL: http://whisperx:8011" not in overlay
    assert "HF_TOKEN: ${HF_TOKEN:-}" in overlay
    assert "HF_TOKEN=" not in (repo / ".env.example").read_text()


def test_docker_build_context_is_allowlisted_and_excludes_private_workspace_data():
    repo = Path(__file__).parents[1]
    rules = [
        line.strip()
        for line in (repo / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert rules[0] == "**"
    assert set(rules[1:]) == {
        "!.dockerignore",
        "!Dockerfile",
        "!pyproject.toml",
        "!uv.lock",
        "!src/",
        "!src/**",
        "!scripts/",
        "!scripts/**",
        "!services/",
        "!services/**",
    }
    assert not any(rule.startswith("!.env") or rule.startswith("!testmedia") for rule in rules)
