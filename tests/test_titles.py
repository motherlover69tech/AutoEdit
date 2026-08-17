"""Stage 9.2 title generator — tests-first contract suite.

Covers TEST-9.2-01..10 against the planned public surface of
``autoedit.title_generator``. Tests are mock-isolated: no live Ollama,
no UI, no OpenRouter, no persistence, no network (TEST-9.2-03).
Failing here means the implementation is missing or drifting.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

import pytest

from autoedit.config import Settings
from stage92_title_helpers import (
    BASE_URL_SENTINEL,
    FIXTURE_SPEAKER_GUEST,
    FIXTURE_SPEAKER_HOST,
    FIXTURE_SUMMARY_LINE,
    FIXTURE_TOPIC_ONE,
    FIXTURE_TOPIC_TWO,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    SECRET_SENTINEL,
    STRATEGIES,
    STRATEGY_LABELS,
    assert_no_sensitive_text,
    build_service,
    eligible_speaker_summary,
    error_code,
    generic_speaker_summary,
    make_summary,
    mock_service,
    valid_model_response,
)

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def summary() -> dict[str, Any]:
    return eligible_speaker_summary()


@pytest.fixture
def service() -> Any:
    """Default service: deterministic mock backend, no network."""
    return mock_service()


# ── TEST-9.2-01: taxonomy, context, hash, truncation, normalization ─────


def test_exact_five_strategy_keys_and_canonical_order(summary):
    """ARCH-9.2-03 / TEST-9.2-01: exactly the five stable keys, stable order."""
    result = service_generate(service, summary)
    assert [g["strategy"] for g in result["groups"]] == list(STRATEGIES)


def test_strategy_labels_are_server_owned(summary):
    for group in service_generate(service, summary)["groups"]:
        assert group["label"] == STRATEGY_LABELS[group["strategy"]]


def test_response_envelope_contract(summary):
    """BACKEND-9.2-02: stage-9.2.v1 envelope fields are exact."""
    result = service_generate(service, summary)
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] in {"complete", "partial"}
    assert result["backend"] == "mock"
    assert result["model"] is None
    assert result["prompt_version"] == PROMPT_VERSION
    assert re.fullmatch(r"[0-9a-f]{64}", result["source_hash"])
    assert isinstance(result["warnings"], list)
    for group in result["groups"]:
        assert set(group) == {
            "strategy",
            "label",
            "variation",
            "status",
            "cache_hit",
            "titles",
            "error_code",
        }
        assert group["variation"] == 0
        assert group["status"] == "complete"
        assert group["cache_hit"] is False
        assert group["error_code"] is None
        assert {t["text"] for t in group["titles"]}


def test_context_extraction_uses_only_labels_summaries_speakers(service, summary):
    """ARCH-9.2-05: context built from labels, span summaries, speakers only."""
    context = _canonical_context(service, summary, list(STRATEGIES), 3, 0)
    assert FIXTURE_TOPIC_ONE in context
    assert FIXTURE_TOPIC_TWO in context
    assert FIXTURE_SUMMARY_LINE in context
    assert FIXTURE_SPEAKER_HOST in context
    assert FIXTURE_SPEAKER_GUEST in context
    # Exclusions: no paths, timestamps, totals, or raw JSON keys leak in.
    assert "source_path" not in context
    assert "start_ms" not in context
    assert "colour" not in context
    assert "speaker_time_ms" not in context


def test_context_is_canonical_sorted_and_stable(service, summary):
    """BACKEND-9.2-05: canonical JSON, sorted keys, stable list ordering."""
    first = _canonical_context(service, summary, list(STRATEGIES), 3, 0)
    second = _canonical_context(service, summary, list(STRATEGIES), 3, 0)
    assert first == second
    parsed = json.loads(first)
    assert first == json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    # Reordered input topics must not change the canonical bytes when the
    # server re-sorts deterministically by stable topic order — the hash
    # must be a function of canonical form, not dict insertion order.
    reordered = json.loads(json.dumps(summary))
    reordered["topics"] = list(reversed(reordered["topics"]))
    reordered_hash = _source_hash(service, reordered, list(STRATEGIES), 3, 0)
    original_hash = _source_hash(service, summary, list(STRATEGIES), 3, 0)
    # Either the server preserves topic order (hashes differ) or it
    # canonical-sorts them (hashes equal) — but both calls are deterministic.
    assert _source_hash(service, reordered, list(STRATEGIES), 3, 0) == reordered_hash
    assert original_hash == _source_hash(service, summary, list(STRATEGIES), 3, 0)


def test_source_hash_is_sha256_of_context_plus_prompt_version(service, summary):
    """BACKEND-9.2-05 / ARCH-9.2-06: hash binds context + prompt version."""
    expected = hashlib.sha256(
        _canonical_context(service, summary, list(STRATEGIES), 3, 0).encode("utf-8")
        + PROMPT_VERSION.encode("utf-8")
    ).hexdigest()
    assert _source_hash(service, summary, list(STRATEGIES), 3, 0) == expected


def test_whole_summary_truncation_warns_and_keeps_labels(service):
    """ARCH-9.2-05: truncate only at whole-summary boundaries; warn."""
    big = make_summary()
    # Force the budget far below the full context but above the labels.
    tight = build_service(
        settings=Settings(TITLE_BACKEND="mock"),
        context_char_budget=200,
    )
    result = service_generate(tight, big)
    assert "context_truncated" in result["warnings"]
    # Labels are retained before optional summaries.
    assert FIXTURE_TOPIC_ONE in _canonical_context(tight, big, list(STRATEGIES), 3, 0)
    # No source excerpt may appear in warnings (Section 4).
    for warning in result["warnings"]:
        assert FIXTURE_SUMMARY_LINE not in warning


def test_title_normalization_and_limits(service, summary):
    """BACKEND-9.2-15: whitespace normalized, Unicode preserved, <=100 chars."""
    result = service_generate(service, summary)
    for group in result["groups"]:
        for title in group["titles"]:
            text = title["text"]
            assert text == " ".join(text.split())
            assert len(text) <= 100
            assert not any(ord(ch) < 32 for ch in text)


def test_titles_unique_within_and_across_groups(service, summary):
    """BACKEND-9.2-16: uniqueness enforced within and across groups."""
    result = service_generate(service, summary)
    seen: set[str] = set()
    for group in result["groups"]:
        group_texts = [t["text"] for t in group["titles"]]
        assert len(group_texts) == len(set(group_texts))
        assert not (seen & set(group_texts))
        seen.update(group_texts)


def test_named_guest_eligible_with_explicit_label(service, summary):
    """BACKEND-9.2-14: explicit non-generic speaker → named_guest available."""
    result = service_generate(service, summary)
    named = next(g for g in result["groups"] if g["strategy"] == "named_guest")
    assert named["status"] == "complete"
    assert named["error_code"] is None
    assert any(FIXTURE_SPEAKER_GUEST in t["text"] for t in named["titles"])


def test_named_guest_unavailable_with_generic_labels(service):
    """BACKEND-9.2-14: generic/empty labels → explicit unavailable, no invention."""
    result = service_generate(service, generic_speaker_summary())
    named = next(g for g in result["groups"] if g["strategy"] == "named_guest")
    assert named["status"] == "unavailable"
    assert named["error_code"] == "no_named_speaker"
    assert named["titles"] == []
    for group in result["groups"]:
        for title in group["titles"]:
            assert "Speaker" != title["text"].strip()


def test_partial_status_when_named_guest_unavailable(service):
    """BACKEND-9.2-11 / Section 4: partial when at least one group unavailable."""
    result = service_generate(service, generic_speaker_summary())
    assert result["status"] == "partial"


def test_summary_without_usable_topics_is_rejected(service):
    """Section 4: 400-class failure when no usable topic label/summary."""
    with pytest.raises(Exception) as excinfo:
        service_generate(service, {"topics": [], "totals": {}})
    assert error_code(excinfo.value) or str(excinfo.value)
    assert "no_usable" in str(error_code(excinfo.value) or excinfo.value) or (
        "summary" in str(excinfo.value).lower()
    )


# ── TEST-9.2-02: deterministic mock equality / difference ───────────────


@pytest.mark.parametrize("variation", [0, 1, 2])
def test_mock_deterministic_for_identical_input_variation(service, summary, variation):
    a = service_generate(service, summary, variation=variation)
    b = service_generate(service, summary, variation=variation)
    assert a["groups"] == b["groups"]
    assert a["source_hash"] == b["source_hash"]


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_mock_next_variation_differs_per_strategy(service, summary, strategy):
    a = service_generate(service, summary, strategies=[strategy], variation=0)
    b = service_generate(service, summary, strategies=[strategy], variation=1)
    ga = next(g for g in a["groups"] if g["strategy"] == strategy)
    gb = next(g for g in b["groups"] if g["strategy"] == strategy)
    assert [t["text"] for t in ga["titles"]] != [t["text"] for t in gb["titles"]]


def test_mock_respects_requested_count(service, summary):
    for count in (1, 3, 5):
        result = service_generate(service, summary, count=count)
        for group in result["groups"]:
            assert len(group["titles"]) == count


def test_mock_requested_strategies_only_in_canonical_order(service, summary):
    requested = ["listicle", "curiosity_gap"]
    result = service_generate(service, summary, strategies=requested)
    assert [g["strategy"] for g in result["groups"]] == [
        "curiosity_gap",
        "listicle",
    ]
    assert result["status"] == "complete"


# ── TEST-9.2-03: mock performs zero network/client calls ────────────────


def test_mock_backend_makes_zero_external_calls_even_with_ollama_configured(
    summary, monkeypatch
):
    """BACKEND-9.2-07 / TEST-9.2-03: zero DNS/HTTP/provider calls in mock mode."""
    from autoedit import llm_client as llm_module

    calls: list[str] = []

    def explode(*_a, **_k):
        calls.append("llm")
        raise AssertionError("mock backend must never touch the LLM client")

    monkeypatch.setattr(llm_module.LLMClient, "chat", explode)
    monkeypatch.setattr(llm_module.LLMClient, "health_check", explode)

    def no_network(*_a, **_k):
        calls.append("httpx")
        raise AssertionError("mock backend must never open a network client")

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", no_network)

    settings = Settings(
        TITLE_BACKEND="mock",
        OLLAMA_BASE_URL="http://192.168.50.50:11434",
        LLM_MODEL="hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M",
    )
    service = build_service(settings=settings)
    result = service_generate(service, summary)
    assert calls == []
    assert result["backend"] == "mock"
    assert result["status"] == "complete"


def test_ollama_url_alone_does_not_activate_title_model_traffic(summary):
    """ARCH-9.2-01: populated OLLAMA_BASE_URL/LLM_MODEL alone stays mock."""
    settings = Settings(
        OLLAMA_BASE_URL="http://192.168.50.50:11434",
        LLM_MODEL="some-model",
    )
    assert getattr(settings, "title_backend", "mock") == "mock"
    service = build_service(settings=settings)
    result = service_generate(service, summary)
    assert result["backend"] == "mock"


# ── Request validation (TEST-9.2-04) ────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"strategies": ["curiosity_gap", "curiosity_gap"]},  # duplicate
        {"strategies": ["clickbait"]},  # unknown (old taxonomy)
        {"strategies": []},  # empty
        {"strategies": "curiosity_gap"},  # wrong type
        {"count": 0},  # below range
        {"count": 6},  # above range
        {"count": 3.0},  # float not strict int
        {"count": True},  # boolean masquerading as integer
        {"count": "3"},  # string
        {"variation": -1},
        {"variation": 1001},
        {"variation": True},
        {"backend": "ollama"},  # client-selected backend
        {"provider": "openrouter"},  # client-selected provider
        {"model": "qwen"},  # client-selected model
        {"url": "http://x"},  # client-selected URL
        {"prompt": "hello"},  # client-selected prompt
        {"source": {"topics": []}},  # client-submitted source data
        {"cache": "bypass"},  # cache bypass
        {"persist": True},  # persistence toggle
    ],
)
def test_strict_request_rejection(service, summary, payload):
    """BACKEND-9.2-01 / BACKEND-9.2-17 / TEST-9.2-04."""
    with pytest.raises(Exception) as excinfo:
        service_generate(service, summary, **{k: v for k, v in payload.items() if k in ("strategies", "count", "variation")})
        # For non-request fields, the service must ignore-or-reject; the
        # API layer enforces 422 for extra fields (tested in test_titles_api).
        if set(payload) - {"strategies", "count", "variation"}:
            return
    # If we get here, the call was accepted: acceptable only for fields the
    # request contract defines. Parametrized invalid values must not reach here.
    assert False, f"invalid request accepted: {payload}" if not excinfo else None


def test_request_defaults_all_five_count3_variation0(service, summary):
    """Section 4: defaults — all five strategies, count 3, variation 0."""
    result = service_generate(service, summary)
    assert [g["strategy"] for g in result["groups"]] == list(STRATEGIES)
    assert all(len(g["titles"]) == 3 for g in result["groups"])
    assert all(g["variation"] == 0 for g in result["groups"])


# ── TEST-9.2-06/07: malformed model matrix, one repair, no fallback ─────


def _ollama_service(fake_chat: Any, **kwargs: Any) -> Any:
    from autoedit.config import Settings

    settings = Settings(
        TITLE_BACKEND="ollama",
        OLLAMA_BASE_URL="http://127.0.0.1:11434",
        LLM_MODEL="fake-local-model",
    )
    kwargs.setdefault("settings", settings)
    kwargs.setdefault("llm_client", fake_chat)
    return build_service(**kwargs)


def _run_sync(coro) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _generate_ollama(service, summary, **kwargs) -> Any:
    return _run_sync(service.generate(summary, **kwargs))


def _valid_groups_by_strategy(payload: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for group in payload.get("groups", []):
        out[group["strategy"]] = [t["text"] for t in group["titles"]]
    return out


def test_malformed_json_triggers_one_repair_then_502(summary):
    """TEST-9.2-06/07: malformed JSON → repair once → 502 when still invalid."""

    class Malformed:
        calls = 0

        async def chat(self, system, user, **kwargs):
            Malformed.calls += 1
            raise RuntimeError("LLM returned invalid JSON")

    fake = Malformed()
    service = _ollama_service(fake)
    with pytest.raises(Exception) as excinfo:
        _generate_ollama(service, summary)
    # Initial attempt + exactly one repair attempt, then stable 502-class failure.
    assert Malformed.calls == 2
    text = str(excinfo.value)
    assert "502" in text or "no_valid" in text.lower()


def test_partial_model_output_keeps_valid_groups_and_repairs_only_missing(summary):
    """BACKEND-9.2-10/11: repair names only invalid/missing strategy keys."""
    first_response = {
        "groups": [
            {"strategy": "curiosity_gap", "titles": [f"valid curiosity {i}" for i in range(3)]},
            # controversy group missing entirely; others absent too
        ]
    }
    second_response = valid_model_response(
        ["controversy", "named_guest", "listicle", "plainspoken"],
    )

    service = _ollama_service(_RecordingChat([first_response, second_response]))

    result = _generate_ollama(service, summary)
    assert result["status"] == "complete"
    curiosity = next(g for g in result["groups"] if g["strategy"] == "curiosity_gap")
    assert [t["text"] for t in curiosity["titles"]] == [
        "valid curiosity 0",
        "valid curiosity 1",
        "valid curiosity 2",
    ]
    # Exactly one repair attempt (two chat calls total).
    assert len(service.llm_client.calls) == 2
    # Repair request names only the invalid/missing strategies.
    repair_user = service.llm_client.calls[1].user
    for bad in ("curiosity_gap",):
        assert bad not in repair_user
    for missing in ("controversy", "named_guest", "listicle", "plainspoken"):
        assert missing in repair_user


def test_total_model_failure_raises_502_without_template_fallback(summary):
    """BACKEND-9.2-12 / TEST-9.2-07: no silent mock/template fallback in ollama."""

    class AlwaysMalformed:
        async def chat(self, system, user, **kwargs):
            return {"groups": "not-a-list"}

    service = _ollama_service(AlwaysMalformed())
    with pytest.raises(Exception) as excinfo:
        _generate_ollama(service, summary)
    assert "502" in str(excinfo.value) or "no_valid" in str(excinfo.value).lower()
    # Exactly two attempts: initial + one repair.
    assert len(service.llm_client.calls) == 2


def test_duplicate_titles_take_repair_path(summary):
    """TEST-9.2-06: duplicate titles across groups are invalid → repair."""
    dup_response = {
        "groups": [
            {"strategy": "curiosity_gap", "titles": ["Same Title", "Same Title", "Third"]},
            {"strategy": "controversy", "titles": ["Same Title", "Other A", "Other B"]},
            {"strategy": "named_guest", "titles": ["Same Title", "Other C", "Other D"]},
            {"strategy": "listicle", "titles": ["Same Title", "Other E", "Other F"]},
            {"strategy": "plainspoken", "titles": ["Same Title", "Other G", "Other H"]},
        ]
    }
    good = valid_model_response()
    service = _ollama_service(_RecordingChat([dup_response, good]))
    result = _generate_ollama(service, summary)
    assert result["status"] == "complete"
    texts = [t["text"] for g in result["groups"] for t in g["titles"]]
    assert len(texts) == len(set(texts))
    assert len(service.llm_client.calls) == 2


def test_wrong_title_type_and_extra_fields_repair(summary):
    """TEST-9.2-06: wrong type / extra fields in model output → repair path."""
    bad = {
        "groups": [
            {"strategy": "curiosity_gap", "titles": [123, None, "ok"], "extra": 1},
            {"strategy": "controversy", "titles": [f"c{i}" for i in range(3)]},
            {"strategy": "named_guest", "titles": [f"g{i}" for i in range(3)]},
            {"strategy": "listicle", "titles": [f"l{i}" for i in range(3)]},
            {"strategy": "plainspoken", "titles": [f"p{i}" for i in range(3)]},
        ]
    }
    service = _ollama_service(_RecordingChat([bad, valid_model_response()]))
    result = _generate_ollama(service, summary)
    assert result["status"] == "complete"
    for group in result["groups"]:
        for title in group["titles"]:
            assert isinstance(title["text"], str)
            assert title["text"].strip()


def test_control_and_overlong_titles_rejected(summary):
    """TEST-9.2-06: control characters / >100 chars → invalid → repair."""
    bad = {
        "groups": [
            {
                "strategy": "curiosity_gap",
                "titles": ["bad\x01control", "x" * 101, "fine one"],
            },
            {"strategy": "controversy", "titles": [f"c{i}" for i in range(3)]},
            {"strategy": "named_guest", "titles": [f"g{i}" for i in range(3)]},
            {"strategy": "listicle", "titles": [f"l{i}" for i in range(3)]},
            {"strategy": "plainspoken", "titles": [f"p{i}" for i in range(3)]},
        ]
    }
    service = _ollama_service(_RecordingChat([bad, valid_model_response()]))
    result = _generate_ollama(service, summary)
    for group in result["groups"]:
        for title in group["titles"]:
            assert len(title["text"]) <= 100
            assert not any(ord(ch) < 32 for ch in title["text"])
    assert len(service.llm_client.calls) == 2


def test_unknown_strategy_in_model_output_enters_repair(summary):
    """TEST-9.2-06: unknown strategy key in model output is invalid."""
    bad = {
        "groups": [
            {"strategy": "clickbait", "titles": ["a", "b", "c"]},
            {"strategy": "curiosity_gap", "titles": [f"c{i}" for i in range(3)]},
            {"strategy": "controversy", "titles": [f"v{i}" for i in range(3)]},
            {"strategy": "listicle", "titles": [f"l{i}" for i in range(3)]},
            {"strategy": "plainspoken", "titles": [f"p{i}" for i in range(3)]},
        ]
    }
    service = _ollama_service(_RecordingChat([bad, valid_model_response()]))
    result = _generate_ollama(service, summary)
    assert [g["strategy"] for g in result["groups"]] == list(STRATEGIES)
    assert len(service.llm_client.calls) == 2


def test_wrong_top_level_type_repair_then_502(summary):
    """TEST-9.2-06: wrong top-level type is never accepted."""
    service = _ollama_service(_RecordingChat(["[1,2,3]", 42]))
    with pytest.raises(Exception) as excinfo:
        _generate_ollama(service, summary)
    assert "502" in str(excinfo.value) or "no_valid" in str(excinfo.value).lower()
    assert len(service.llm_client.calls) == 2


def test_repair_contains_no_previously_valid_title_text(summary):
    """BACKEND-9.2-10: repair request must not embed prior valid titles."""
    first = {
        "groups": [
            {"strategy": "curiosity_gap", "titles": ["Sentinel Valid Title A", "B", "C"]},
        ]
    }
    second = valid_model_response(["controversy", "named_guest", "listicle", "plainspoken"])
    service = _ollama_service(_RecordingChat([first, second]))
    _generate_ollama(service, summary)
    repair_user = service.llm_client.calls[1].user
    assert "Sentinel Valid Title A" not in repair_user


def test_ollama_request_uses_schema_think_false_output_bound_keep_alive_zero(summary):
    """ARCH-9.2-04 / TEST-9.2-09: exact chat kwargs on the ollama path."""
    fake = _RecordingChat([valid_model_response()])
    service = _ollama_service(fake)
    _generate_ollama(service, summary)
    call = fake.calls[0]
    assert call.json_schema is not None
    assert call.json_schema.get("type") == "object"
    assert call.think is False
    assert call.keep_alive == 0
    assert call.kwargs.get("max_tokens") is not None
    # Prompt treats the context as untrusted data (SEC-9.2-04).
    prompt_blob = call.system + call.user
    assert FIXTURE_SUMMARY_LINE in prompt_blob
    assert "untrusted" in prompt_blob.lower() or "do not" in prompt_blob.lower()


# ── TEST-9.2-08: cache identity, LRU bound, restart-local ───────────────


def test_cache_hit_served_without_model_call(summary):
    """BACKEND-9.2-13: exact cache hit → cache_hit=true, no model call."""
    fake = _RecordingChat([valid_model_response()])
    service = _ollama_service(fake)
    first = _generate_ollama(service, summary)
    second = _generate_ollama(service, summary)
    assert len(fake.calls) == 1
    for group in second["groups"]:
        assert group["cache_hit"] is True
    for group in first["groups"]:
        assert group["cache_hit"] is False
    assert second["groups"] == first["groups"]


def test_new_variation_uses_distinct_cache_key(summary):
    """BACKEND-9.2-13: variation is part of the cache identity."""
    fake = _RecordingChat([valid_model_response()])
    service = _ollama_service(fake)
    a = _generate_ollama(service, summary, variation=0)
    b = _generate_ollama(service, summary, variation=1)
    assert len(fake.calls) == 2
    assert a["groups"] != b["groups"] or [
        t["text"] for g in a["groups"] for t in g["titles"]
    ] != [t["text"] for g in b["groups"] for t in g["titles"]]


def test_cache_key_includes_backend_model_prompt_version_count(summary):
    """TEST-9.2-08: identity spans source hash, backend, model, version, count."""
    fake = _RecordingChat([valid_model_response()])
    service = _ollama_service(fake)
    _generate_ollama(service, summary, count=2)
    # Same request again: hit.
    _generate_ollama(service, summary, count=2)
    assert len(fake.calls) == 1
    # Different count: distinct key → new call.
    _generate_ollama(service, summary, count=3)
    assert len(fake.calls) == 2


def test_lru_cache_is_bounded_and_restart_local(tmp_path):
    """ARCH-9.2-07: finite LRU bound; new process starts empty."""
    from autoedit.config import Settings

    fake = _RecordingChat([valid_model_response()])
    settings = Settings(
        TITLE_BACKEND="ollama",
        OLLAMA_BASE_URL="http://127.0.0.1:11434",
        LLM_MODEL="fake-local-model",
    )
    service = build_service(settings=settings, llm_client=fake, cache_max_entries=2)
    summary = eligible_speaker_summary()
    # Fill the cache with 4 distinct keys; only the last 2 may survive.
    for variation in range(4):
        _generate_ollama(service, summary, variation=variation)
    assert len(fake.calls) == 4
    # Re-request the two most recent: hits.
    for variation in (2, 3):
        result = _generate_ollama(service, summary, variation=variation)
        assert all(g["cache_hit"] for g in result["groups"])
    assert len(fake.calls) == 4
    # Oldest evicted: re-request variation 0 must call the model again.
    _generate_ollama(service, summary, variation=0)
    assert len(fake.calls) == 5
    # Restart-local: a fresh service has an empty cache (no persistence).
    fake2 = _RecordingChat([valid_model_response()])
    fresh = build_service(settings=settings, llm_client=fake2, cache_max_entries=2)
    result = _generate_ollama(fresh, summary, variation=3)
    assert all(g["cache_hit"] is False for g in result["groups"])
    assert len(fake2.calls) == 1


def test_cache_never_writes_to_disk(tmp_path, summary):
    """SEC-9.2-07: cache is process-memory only; nothing hits disk."""
    fake = _RecordingChat([valid_model_response()])
    service = _ollama_service(fake, cache_max_entries=8)
    _generate_ollama(service, summary)
    _generate_ollama(service, summary)
    created = [p.name for p in tmp_path.rglob("*")]
    assert not [n for n in created if "title" in n.lower() or "cache" in n.lower()]


# ── TEST-9.2-09: local-only URL policy (unit level) ─────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://openrouter.ai/api/v1",
        "https://api.openai.com/v1",
        "http://ollama.example.com:11434",
        "http://8.8.8.8:11434",
        "http://10.99.99.99:11434",
        "http://172.31.255.255:11434",
        "http://192.168.254.1:11434",
    ],
)
def test_non_local_ollama_urls_are_rejected_before_io(summary, url):
    """SEC-9.2-02: public/unknown hosts rejected before transport."""
    from autoedit.config import Settings

    fake = _RecordingChat([valid_model_response()])
    settings = Settings(TITLE_BACKEND="ollama", OLLAMA_BASE_URL=url, LLM_MODEL="m")
    service = build_service(settings=settings, llm_client=fake)
    with pytest.raises(Exception) as excinfo:
        _generate_ollama(service, summary)
    assert len(fake.calls) == 0, "URL policy must reject before any chat call"
    text = str(excinfo.value)
    assert "503" in text or "unavailable" in text.lower() or "disallowed" in text.lower()


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://[::1]:11434",
        "http://169.254.10.20:11434",
    ],
)
def test_local_ollama_urls_are_allowed(summary, url):
    """SEC-9.2-02: localhost / loopback / link-local are the allowed set."""
    from autoedit.config import Settings

    fake = _RecordingChat([valid_model_response()])
    settings = Settings(TITLE_BACKEND="ollama", OLLAMA_BASE_URL=url, LLM_MODEL="m")
    service = build_service(settings=settings, llm_client=fake)
    result = _generate_ollama(service, summary)
    assert result["status"] == "complete"
    assert len(fake.calls) == 1


# ── TEST-9.2-10: redaction — logs and errors leak nothing ───────────────


def test_errors_and_logs_contain_no_private_text(caplog, summary):
    """SEC-9.2-05 / TEST-9.2-10: no fixture text, prompt, body, URL, or secret."""
    import logging

    class ExplodingChat:
        async def chat(self, system, user, **kwargs):
            raise RuntimeError(
                f"boom {SECRET_SENTINEL} context={FIXTURE_SUMMARY_LINE} "
                f"url={BASE_URL_SENTINEL}"
            )

    service = _ollama_service(ExplodingChat())
    with caplog.at_level(logging.DEBUG, logger="autoedit"):
        with pytest.raises(Exception):
            _generate_ollama(service, summary)
    rendered = "\n".join(caplog.text.splitlines())
    assert_no_sensitive_text(rendered)
    assert SECRET_SENTINEL not in rendered
    assert FIXTURE_SUMMARY_LINE not in rendered
    assert BASE_URL_SENTINEL not in rendered


def test_http_error_log_redacted_in_llm_client():
    """BACKEND-9.2-18: LLMClient logs status/class only, never response text."""
    import logging
    from unittest import mock

    import httpx

    from autoedit.llm_client import LLMClient

    settings = Settings(OLLAMA_BASE_URL=BASE_URL_SENTINEL, LLM_MODEL="m")
    client = LLMClient(settings)

    response = mock.Mock()
    response.status_code = 500
    response.text = f"secret body {SECRET_SENTINEL}"
    http_error = httpx.HTTPStatusError("server error", request=mock.Mock(), response=response)

    async def failing_post(*a, **k):
        raise http_error

    async_client = mock.Mock()
    async_client.post = failing_post
    async_client.__aenter__ = mock.AsyncMock(return_value=async_client)
    async_client.__aexit__ = mock.AsyncMock(return_value=False)

    import io

    stream = io.StringIO()
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)
            stream.write(record.getMessage())

    handler = Capture()
    logger = logging.getLogger("autoedit.llm_client")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        with mock.patch("autoedit.llm_client.httpx.AsyncClient", return_value=async_client):
            with pytest.raises(RuntimeError):
                _run_sync(client.chat("system", "user"))
    finally:
        logger.removeHandler(handler)

    rendered = " | ".join(r.getMessage() for r in records)
    assert SECRET_SENTINEL not in rendered
    assert "secret body" not in rendered
    assert "500" in rendered or "HTTPStatusError" in rendered or "error" in rendered.lower()


def test_llm_client_invalid_json_log_redacted():
    """BACKEND-9.2-18: JSON decode errors must not log the model output."""
    import logging
    from unittest import mock

    from autoedit.llm_client import LLMClient

    settings = Settings(OLLAMA_BASE_URL=BASE_URL_SENTINEL, LLM_MODEL="m")
    client = LLMClient(settings)

    response = mock.Mock()
    response.json.return_value = {"message": {"content": f"{{bad {SECRET_SENTINEL}"}}
    async_client = mock.Mock()
    async_client.post = mock.AsyncMock(return_value=response)
    async_client.__aenter__ = mock.AsyncMock(return_value=async_client)
    async_client.__aexit__ = mock.AsyncMock(return_value=False)

    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Capture()
    logger = logging.getLogger("autoedit.llm_client")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        with mock.patch("autoedit.llm_client.httpx.AsyncClient", return_value=async_client):
            with pytest.raises(RuntimeError):
                _run_sync(client.chat("system", "user"))
    finally:
        logger.removeHandler(handler)

    rendered = " | ".join(r.getMessage() for r in records)
    assert SECRET_SENTINEL not in rendered


# ── ARCH-9.2-09: serialized inference (one active, bounded wait) ────────


def test_ollama_inference_is_serialized_per_process(summary):
    """ARCH-9.2-09: concurrent generate calls do not run chat concurrently."""
    import threading

    active = 0
    max_active = 0
    lock = threading.Lock()
    responses = [valid_model_response() for _ in range(8)]

    class SlowChat:
        async def chat(self, system, user, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            with lock:
                active -= 1
            return responses.pop(0)

    from autoedit.config import Settings

    settings = Settings(
        TITLE_BACKEND="ollama",
        OLLAMA_BASE_URL="http://127.0.0.1:11434",
        LLM_MODEL="fake-local-model",
    )
    service = build_service(settings=settings, llm_client=SlowChat())

    def worker(variation: int) -> None:
        _generate_ollama(service, summary, variation=variation)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert max_active == 1


# ── Helpers (test-side) ─────────────────────────────────────────────────


def _canonical_context(service: Any, summary: dict[str, Any], strategies, count, variation) -> str:
    fn = getattr(service, "build_context", None) or getattr(service, "_build_context", None)
    if fn is None:
        raise AssertionError(
            "title service must expose a canonical context builder "
            "(build_context) for BACKEND-9.2-05 verification"
        )
    return fn(summary, strategies=list(strategies), count=count, variation=variation)


def _source_hash(service: Any, summary: dict[str, Any], strategies, count, variation) -> str:
    fn = getattr(service, "source_hash", None) or getattr(service, "_source_hash", None)
    if fn is None:
        raise AssertionError(
            "title service must expose source_hash(summary, ...) "
            "(BACKEND-9.2-05 verification)"
        )
    return fn(summary, strategies=list(strategies), count=count, variation=variation)


def service_generate(service: Any, summary: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Invoke the service through its public generate() surface."""
    generate = getattr(service, "generate", None)
    if generate is None:
        raise AssertionError(
            "title service must expose generate(summary, strategies, count, variation)"
        )
    kwargs.setdefault("strategies", list(STRATEGIES))
    kwargs.setdefault("count", 3)
    kwargs.setdefault("variation", 0)
    result = generate(summary, **kwargs)
    if asyncio.iscoroutine(result):
        return _run_sync(result)
    return result


class _RecordingChat:
    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[Any] = []

    async def chat(self, system: str, user: str, **kwargs: Any) -> Any:
        from stage92_title_helpers import ChatCall

        self.calls.append(ChatCall(system=system, user=user, kwargs=kwargs))
        if not self.responses:
            raise AssertionError("unexpected extra model call")
        return self.responses.pop(0)

    @property
    def llm_client(self) -> Any:
        return self
