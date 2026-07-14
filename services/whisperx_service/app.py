from __future__ import annotations

import hashlib
import heapq
import inspect
import logging
import math
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.whisperx_service.jobs import GPUJobManager, GPUJobQueueFull, JobNotFoundError


DATA_ROOT = os.getenv("DATA_ROOT", "/data")
DEVICE = os.getenv("WHISPERX_DEVICE", "cuda")
ALLOWED_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
ALLOWED_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
MAX_BATCH_SIZE = int(os.getenv("WHISPER_BATCH_SIZE", "4"))
ALLOWED_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en").strip() or None
ALIGN_ENABLED = os.getenv("WHISPER_ALIGN", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DIARIZE_ENABLED = os.getenv("WHISPER_DIARIZE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DIARIZATION_MODEL = os.getenv(
    "WHISPER_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)
_model_lock = threading.Lock()
logger = logging.getLogger(__name__)


class TranscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_path: str
    model: str = "large-v3"
    language: str | None = "en"
    batch_size: int = Field(default=4, ge=1, le=64)
    compute_type: str = "float16"
    align: bool = True


class AnalyzeRequest(TranscribeRequest):
    input_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    diarize: bool = False
    min_speakers: int | None = Field(default=None, ge=1, le=16)
    max_speakers: int | None = Field(default=None, ge=1, le=16)



def resolve_shared_audio_path(audio_path: str | Path, data_root: str | Path) -> Path:
    """Resolve an input and confine it to the worker's read-only shared root."""
    root = Path(data_root).resolve()
    candidate = Path(audio_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("audio_path must stay inside DATA_ROOT") from exc
    if not resolved.is_file():
        raise FileNotFoundError("audio file not found")
    return resolved


@lru_cache(maxsize=2)
def _load_asr_model(model_name: str, compute_type: str):
    import whisperx

    return whisperx.load_model(model_name, DEVICE, compute_type=compute_type)


@lru_cache(maxsize=8)
def _load_alignment_model(language: str):
    import whisperx

    return whisperx.load_align_model(language_code=language, device=DEVICE)


def run_whisperx(request: TranscribeRequest) -> dict[str, Any]:
    """Run WhisperX ASR and optional forced alignment under a GPU lock."""
    if request.model != ALLOWED_MODEL:
        raise ValueError(f"model must be {ALLOWED_MODEL!r}")
    if request.compute_type != ALLOWED_COMPUTE_TYPE:
        raise ValueError(f"compute_type must be {ALLOWED_COMPUTE_TYPE!r}")
    if request.batch_size > MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must not exceed {MAX_BATCH_SIZE}")
    if request.language != ALLOWED_LANGUAGE:
        raise ValueError(f"language must be {ALLOWED_LANGUAGE!r}")
    if request.align != ALIGN_ENABLED:
        raise ValueError(f"align must be {ALIGN_ENABLED!r}")
    audio_path = resolve_shared_audio_path(request.audio_path, DATA_ROOT)
    import whisperx

    with _model_lock:
        model = _load_asr_model(request.model, request.compute_type)
        audio = whisperx.load_audio(str(audio_path))
        transcribe_kwargs: dict[str, Any] = {"batch_size": request.batch_size}
        if request.language:
            transcribe_kwargs["language"] = request.language
        result = model.transcribe(audio, **transcribe_kwargs)

        language = result.get("language") or request.language
        if request.align and language and result.get("segments"):
            align_model, metadata = _load_alignment_model(language)
            result = whisperx.align(
                result["segments"],
                align_model,
                metadata,
                audio,
                DEVICE,
                return_char_alignments=False,
            )
            result["language"] = language

    return {
        "language": result.get("language") or request.language,
        "segments": result.get("segments", []),
    }


def _sha256_file(path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _load_diarization_pipeline():
    # WhisperX 3.8.x exposes this class from the diarize submodule rather than
    # its package root. Keep the import lazy so ASR-only workers do not require
    # gated diarization model access during startup.
    from whisperx.diarize import DiarizationPipeline

    kwargs: dict[str, Any] = {"device": DEVICE}
    signature = inspect.signature(DiarizationPipeline)
    if "model_name" in signature.parameters:
        kwargs["model_name"] = DIARIZATION_MODEL
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if token:
        token_arg = "token" if "token" in signature.parameters else "use_auth_token"
        kwargs[token_arg] = token
    return DiarizationPipeline(**kwargs)


def _normalize_diarization_turns(raw: Any) -> list[dict[str, Any]]:
    if hasattr(raw, "to_dict"):
        rows = raw.to_dict("records")
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = []
    turns: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("diarization rows must be objects")
        start = row.get("start")
        end = row.get("end")
        speaker = row.get("speaker")
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError("diarization timestamps must be numeric")
        start_value = float(start)
        end_value = float(end)
        if not math.isfinite(start_value) or not math.isfinite(end_value):
            raise ValueError("diarization timestamps must be finite")
        if start_value < 0 or end_value <= start_value or not isinstance(speaker, str) or not speaker:
            raise ValueError("invalid diarization turn")
        turns.append(
            {
                "turn_id": f"turn-{index + 1}",
                "diarizer_speaker_id": speaker,
                "start": start_value,
                "end": end_value,
                "overlap": bool(row.get("overlap", False)),
            }
        )

    # Pyannote commonly represents overlap as intersecting speaker turns rather
    # than adding an explicit flag. Two directional sweeps let every turn ask
    # whether any different speaker intersects it without enumerating all
    # intersecting pairs (O(n log n), including adversarial concurrent input).
    ordered = sorted(turns, key=lambda item: (item["start"], item["end"]))

    def best_other(
        heap: list[tuple[float, str]],
        best_by_speaker: dict[str, float],
        excluded_speaker: str,
    ) -> float | None:
        while heap and best_by_speaker.get(heap[0][1]) != heap[0][0]:
            heapq.heappop(heap)
        if not heap:
            return None
        excluded_entry: tuple[float, str] | None = None
        if heap[0][1] == excluded_speaker:
            excluded_entry = heapq.heappop(heap)
            while heap and best_by_speaker.get(heap[0][1]) != heap[0][0]:
                heapq.heappop(heap)
        result = heap[0][0] if heap else None
        if excluded_entry is not None:
            heapq.heappush(heap, excluded_entry)
        return result

    latest_end_heap: list[tuple[float, str]] = []
    latest_end_by_speaker: dict[str, float] = {}
    for turn in ordered:
        speaker = turn["diarizer_speaker_id"]
        neg_latest_other_end = best_other(
            latest_end_heap, latest_end_by_speaker, speaker
        )
        if neg_latest_other_end is not None and -neg_latest_other_end > turn["start"]:
            turn["overlap"] = True
        neg_end = -turn["end"]
        if neg_end < latest_end_by_speaker.get(speaker, math.inf):
            latest_end_by_speaker[speaker] = neg_end
            heapq.heappush(latest_end_heap, (neg_end, speaker))

    earliest_start_heap: list[tuple[float, str]] = []
    earliest_start_by_speaker: dict[str, float] = {}
    for turn in reversed(ordered):
        speaker = turn["diarizer_speaker_id"]
        earliest_other_start = best_other(
            earliest_start_heap, earliest_start_by_speaker, speaker
        )
        if earliest_other_start is not None and earliest_other_start < turn["end"]:
            turn["overlap"] = True
        start = turn["start"]
        if start < earliest_start_by_speaker.get(speaker, math.inf):
            earliest_start_by_speaker[speaker] = start
            heapq.heappush(earliest_start_heap, (start, speaker))

    return turns


def run_analysis(request: AnalyzeRequest) -> dict[str, Any]:
    if request.diarize != DIARIZE_ENABLED:
        raise ValueError(f"diarize must be {DIARIZE_ENABLED!r}")
    if (
        request.min_speakers is not None
        and request.max_speakers is not None
        and request.min_speakers > request.max_speakers
    ):
        raise ValueError("min_speakers must not exceed max_speakers")
    audio_path = resolve_shared_audio_path(request.audio_path, DATA_ROOT)
    if _sha256_file(audio_path) != request.input_sha256:
        raise ValueError("input_sha256 does not match audio input")

    result = run_whisperx(
        TranscribeRequest(
            **request.model_dump(
                exclude={"input_sha256", "diarize", "min_speakers", "max_speakers"}
            )
        )
    )
    turns: list[dict[str, Any]] = []
    if request.diarize:
        import whisperx

        with _model_lock:
            audio = whisperx.load_audio(str(audio_path))
            diarize_kwargs = {
                key: value
                for key, value in {
                    "min_speakers": request.min_speakers,
                    "max_speakers": request.max_speakers,
                }.items()
                if value is not None
            }
            turns = _normalize_diarization_turns(
                _load_diarization_pipeline()(audio, **diarize_kwargs)
            )
    return {
        **result,
        "diarization_turns": turns,
        "models": {
            "asr": ALLOWED_MODEL,
            "alignment": ALIGN_ENABLED,
            "diarization": DIARIZATION_MODEL if request.diarize else None,
        },
    }


_job_manager = GPUJobManager(run_analysis)


app = FastAPI(title="AUTOEDIT WhisperX Service", version="1")


@app.get("/health")
def health() -> dict[str, str]:
    """Cheap process liveness check; this does not claim GPU readiness."""
    return {"status": "alive"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    """Verify CUDA/FP16 and eagerly load the configured ASR model."""
    try:
        import torch
        import whisperx  # noqa: F401

        if DEVICE != "cuda" or not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable")
        capability = torch.cuda.get_device_capability()
        if capability < (7, 0):
            raise RuntimeError("GPU compute capability is below 7.0")
        probe = torch.ones(1, device="cuda", dtype=torch.float16)
        if float((probe + probe).item()) != 2.0:
            raise RuntimeError("CUDA FP16 probe failed")
        _load_asr_model(ALLOWED_MODEL, ALLOWED_COMPUTE_TYPE)
        if DIARIZE_ENABLED:
            _load_diarization_pipeline()
    except Exception as exc:
        logger.exception("WhisperX readiness check failed")
        raise HTTPException(
            status_code=503,
            detail="WhisperX worker is not ready",
        ) from exc
    return {
        "status": "ready",
        "device": DEVICE,
        "model": ALLOWED_MODEL,
        "compute_type": ALLOWED_COMPUTE_TYPE,
        "compute_capability": list(capability),
    }


@app.post("/v1/transcribe")
def transcribe(request: TranscribeRequest) -> dict[str, Any]:
    try:
        return run_whisperx(request)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("WhisperX transcription failed")
        raise HTTPException(
            status_code=500,
            detail="WhisperX transcription failed",
        ) from exc


@app.post("/v1/analyze", status_code=202)
def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    try:
        audio_path = resolve_shared_audio_path(request.audio_path, DATA_ROOT)
        if _sha256_file(audio_path) != request.input_sha256:
            raise ValueError("input_sha256 does not match audio input")
        if request.model != ALLOWED_MODEL:
            raise ValueError(f"model must be {ALLOWED_MODEL!r}")
        if request.compute_type != ALLOWED_COMPUTE_TYPE:
            raise ValueError(f"compute_type must be {ALLOWED_COMPUTE_TYPE!r}")
        if request.batch_size > MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must not exceed {MAX_BATCH_SIZE}")
        if request.language != ALLOWED_LANGUAGE:
            raise ValueError(f"language must be {ALLOWED_LANGUAGE!r}")
        if request.align != ALIGN_ENABLED:
            raise ValueError(f"align must be {ALIGN_ENABLED!r}")
        if request.diarize != DIARIZE_ENABLED:
            raise ValueError(f"diarize must be {DIARIZE_ENABLED!r}")
        if (
            request.min_speakers is not None
            and request.max_speakers is not None
            and request.min_speakers > request.max_speakers
        ):
            raise ValueError("min_speakers must not exceed max_speakers")
        return _job_manager.submit(request)
    except GPUJobQueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return _job_manager.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    try:
        return _job_manager.cancel(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
