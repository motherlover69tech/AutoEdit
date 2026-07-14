from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

import autoedit.llm_client as llm_module
from autoedit.ai.speaker_context import (
    SpeakerContextResult,
    SpeakerNameCandidate,
    extract_speaker_name_candidates,
)
from autoedit.llm_client import LLMClient


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.call = None

    async def chat(self, system, user, **kwargs):
        self.call = (system, user, kwargs)
        return self.response


def _candidate(**updates):
    value = {
        "name": "Barry",
        "evidence_quote": "Any comments, Barry?",
        "start_seconds": 255.322,
        "confidence": 0.4,
        "basis": "explicit_address_or_reference",
    }
    value.update(updates)
    return value


def _extract(response, segments=None):
    client = FakeLLM(response)
    result = asyncio.run(
        extract_speaker_name_candidates(
            segments
            or [{"start": 255.322, "end": 256.0, "text": "Any comments, Barry?"}],
            client=client,
        )
    )
    return result, client


def test_extracts_structured_audit_only_name_context():
    result, client = _extract(
        {"candidates": [_candidate()], "notes": "Explicit address only."}
    )

    assert result.candidates[0].name == "Barry"
    system, user, kwargs = client.call
    assert "Never assign a name" in system
    assert user == "[255.322-256.000] Any comments, Barry?"
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 600
    assert kwargs["think"] is False
    assert kwargs["keep_alive"] == 0
    assert kwargs["json_schema"] == SpeakerContextResult.model_json_schema()


def test_empty_transcript_does_not_call_llm():
    client = FakeLLM({"unexpected": True})
    assert asyncio.run(extract_speaker_name_candidates([], client=client)) == SpeakerContextResult(
        candidates=[], notes=""
    )
    assert client.call is None


def test_valid_empty_model_result_is_accepted():
    result, _ = _extract({"candidates": [], "notes": ""})
    assert result == SpeakerContextResult(candidates=[], notes="")


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"notes": "missing candidates"},
        {"candidates": []},
        {"candidates": {}, "notes": ""},
        {"candidates": [], "notes": "", "unknown": True},
        {"candidates": [{"name": "Barry"}], "notes": ""},
    ],
)
def test_malformed_model_results_are_rejected(response):
    with pytest.raises(ValidationError):
        _extract(response)


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(evidence_quote="fabricated quote"),
        _candidate(start_seconds=999.0),
        _candidate(evidence_quote="Unrelated words", start_seconds=1.0),
    ],
)
def test_candidate_quote_and_timestamp_must_ground_to_same_segment(candidate):
    segments = [
        {"start": 1.0, "end": 2.0, "text": "Any comments, Barry?"},
        {"start": 255.0, "end": 256.0, "text": "Unrelated words"},
    ]
    with pytest.raises(ValueError, match="not grounded"):
        _extract({"candidates": [candidate], "notes": ""}, segments)


def test_candidate_name_must_be_explicitly_grounded_in_evidence_quote():
    with pytest.raises(ValueError, match="name is not grounded"):
        _extract(
            {
                "candidates": [_candidate(name="Alice")],
                "notes": "Grounded quote paired with a hallucinated name.",
            }
        )


def test_thinking_trace_is_rejected_even_inside_valid_json_string():
    with pytest.raises(ValueError, match="thinking trace"):
        _extract({"candidates": [], "notes": "<think>private chain</think>"})


@pytest.mark.parametrize(
    "segment",
    [
        {},
        {"start": True, "end": 2.0, "text": "text"},
        {"start": 1.0, "end": False, "text": "text"},
        {"start": "1", "end": 2.0, "text": "text"},
        {"start": 1.0, "end": 2.0, "text": 123},
        {"start": 1.0, "end": 2.0, "text": "   "},
        {"start": float("nan"), "end": 2.0, "text": "text"},
        {"start": 1.0, "end": float("inf"), "text": "text"},
        {"start": -1.0, "end": 2.0, "text": "text"},
        {"start": 2.0, "end": 1.0, "text": "text"},
        {"start": 1.0, "end": 1.0, "text": "text"},
    ],
)
def test_malformed_transcript_fails_before_llm(segment):
    client = FakeLLM({"candidates": [], "notes": ""})
    with pytest.raises(ValueError, match="invalid transcript segment"):
        asyncio.run(extract_speaker_name_candidates([segment], client=client))
    assert client.call is None


@pytest.mark.parametrize(
    ("basis", "confidence"),
    [
        ("explicit_address_or_reference", 0.4),
        ("uncertain_context", 0.25),
    ],
)
def test_confidence_ceiling_boundaries_are_accepted(basis, confidence):
    candidate = _candidate(basis=basis, confidence=confidence)
    assert SpeakerNameCandidate.model_validate(candidate).confidence == confidence


@pytest.mark.parametrize(
    ("basis", "confidence"),
    [
        ("explicit_address_or_reference", 0.400001),
        ("uncertain_context", 0.250001),
        ("explicit_self_introduction", float("nan")),
        ("explicit_self_introduction", float("inf")),
    ],
)
def test_over_ceiling_or_nonfinite_confidence_is_rejected(basis, confidence):
    with pytest.raises(ValidationError):
        SpeakerNameCandidate.model_validate(_candidate(basis=basis, confidence=confidence))


@pytest.mark.parametrize("assignment_field", ["speaker_id", "diarizer_speaker_id"])
def test_candidate_contract_rejects_voice_cluster_assignment_fields(assignment_field):
    candidate = _candidate()
    candidate[assignment_field] = "invented"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SpeakerNameCandidate.model_validate(candidate)


def test_name_candidate_contract_rejects_coercion():
    with pytest.raises(ValidationError):
        SpeakerNameCandidate.model_validate(_candidate(start_seconds="255.322"))


def test_llm_client_posts_structured_nonthinking_immediate_unload_payload(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": json.dumps({"candidates": [], "notes": ""}),
                }
            }

    class AsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            captured["url"] = url
            captured["payload"] = json
            return Response()

    class Settings:
        ollama_base_url = "http://ollama.test"
        llm_model = "local-test-model"

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", AsyncClient)
    schema = SpeakerContextResult.model_json_schema()
    result = asyncio.run(
        LLMClient(Settings()).chat(
            "system",
            "user",
            temperature=0.0,
            max_tokens=600,
            json_schema=schema,
            think=False,
            keep_alive=0,
        )
    )

    assert result == {"candidates": [], "notes": ""}
    assert captured["payload"]["format"] == schema
    assert captured["payload"]["think"] is False
    assert captured["payload"]["keep_alive"] == 0
    assert captured["payload"]["options"] == {"temperature": 0.0, "num_predict": 600}


@pytest.mark.parametrize(
    "message",
    [
        {"content": json.dumps({"candidates": [], "notes": ""}), "thinking": "trace"},
        {"content": json.dumps({"candidates": [], "notes": "<think>trace</think>"})},
    ],
)
def test_llm_client_rejects_thinking_before_json_parse(monkeypatch, message):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": message}

    class AsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            return Response()

    class Settings:
        ollama_base_url = "http://ollama.test"
        llm_model = "local-test-model"

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", AsyncClient)
    with pytest.raises(RuntimeError, match="thinking trace"):
        asyncio.run(LLMClient(Settings()).chat("system", "user", think=False))
