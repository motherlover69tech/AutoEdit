"""Shared helpers for the Stage 9.2 title-generator test suite.

This module is test scaffolding only — it must never import product code.
It defines the fixture vocabulary, the canonical strategy constants, and
fake LLM transports used by ``test_titles.py`` and ``test_titles_api.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Canonical Stage 9.2 taxonomy (spec Section 1 / ARCH-9.2-03) ──────────
STRATEGIES: tuple[str, ...] = (
    "curiosity_gap",
    "controversy",
    "named_guest",
    "listicle",
    "plainspoken",
)

STRATEGY_LABELS: dict[str, str] = {
    "curiosity_gap": "Curiosity gap",
    "controversy": "Controversy",
    "named_guest": "Named guest",
    "listicle": "Listicle",
    "plainspoken": "Plainspoken",
}

SCHEMA_VERSION = "stage-9.2.v1"
PROMPT_VERSION = "youtube_titles.v1"

# Fictional, consent-cleared fixture vocabulary only (OPS-9.2-10).
FIXTURE_TOPIC_ONE = "Fictional Climate Policy Panel"
FIXTURE_TOPIC_TWO = "Fictional Urban Farming Debate"
FIXTURE_SUMMARY_LINE = (
    "Fictional moderator discussed the fictional climate panel with the "
    "fictional urban farming guest"
)
FIXTURE_SPEAKER_HOST = "FictionalHost"
FIXTURE_SPEAKER_GUEST = "FictionalGuest"

# Sentinel strings that must never appear in logs or API error detail
# (SEC-9.2-05 / TEST-9.2-10).
SECRET_SENTINEL = "fixture-secret-sentinel-90210"
BASE_URL_SENTINEL = "http://ollama.local.invalid:11434"


def make_summary(
    *,
    topics: list[dict[str, Any]] | None = None,
    speakers: list[str] | None = None,
) -> dict[str, Any]:
    """Build a summary.json-shaped dict (spec Section 5.5)."""
    if topics is None:
        topics = [
            {
                "label": FIXTURE_TOPIC_ONE,
                "colour": "#112233",
                "spans": [
                    {
                        "start_ms": 0,
                        "end_ms": 60000,
                        "summary": FIXTURE_SUMMARY_LINE,
                    }
                ],
            },
            {
                "label": FIXTURE_TOPIC_TWO,
                "colour": "#445566",
                "spans": [
                    {
                        "start_ms": 60000,
                        "end_ms": 120000,
                        "summary": "Second fictional span summary",
                    }
                ],
            },
        ]
    if speakers is None:
        speakers = [FIXTURE_SPEAKER_HOST, FIXTURE_SPEAKER_GUEST]
    speaker_time = {name: 30000 for name in speakers}
    for i, topic in enumerate(topics):
        topic = dict(topic)
        topic.setdefault(
            "speaker_time_ms", {name: 15000 for name in speakers[: max(1, len(speakers) - i)]}
        )
        topics[i] = topic
    totals: dict[str, Any] = {
        "speaker_time_ms": dict(speaker_time),
        "talk_overlap_ms": 0,
        "silence_ms": 0,
    }
    return {"topics": topics, "totals": totals}


def eligible_speaker_summary() -> dict[str, Any]:
    """Summary with an explicit, non-generic speaker label (named_guest eligible)."""
    return make_summary()


def generic_speaker_summary() -> dict[str, Any]:
    """Summary whose speaker labels are generic/empty (named_guest ineligible)."""
    return make_summary(speakers=["Speaker", "speaker 1", ""])


def valid_model_response(
    strategies: list[str] | None = None,
    count: int = 3,
    *,
    suffix: str = "",
) -> dict[str, Any]:
    """Build a schema-valid model payload with unique titles across groups."""
    if strategies is None:
        strategies = list(STRATEGIES)
    groups = []
    for idx, strategy in enumerate(strategies):
        titles = [
            f"{strategy} title {n} {idx} {suffix}".strip()
            for n in range(1, count + 1)
        ]
        groups.append({"strategy": strategy, "titles": titles})
    return {"groups": groups}


@dataclass
class ChatCall:
    system: str
    user: str
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def json_schema(self) -> Any:
        return self.kwargs.get("json_schema")

    @property
    def think(self) -> Any:
        return self.kwargs.get("think")

    @property
    def keep_alive(self) -> Any:
        return self.kwargs.get("keep_alive")


@dataclass
class FakeChat:
    """In-process stand-in for the LLM chat surface (no network, ever)."""

    model: str = "fake-local-model"
    responses: list[Any] = field(default_factory=list)
    calls: list[ChatCall] = field(default_factory=list)
    default: Any = None

    async def chat(self, system: str, user: str, **kwargs: Any) -> Any:
        self.calls.append(ChatCall(system=system, user=user, kwargs=kwargs))
        if self.responses:
            if len(self.responses) > 1:
                return self.responses.pop(0)
            return self.responses[0]
        return self.default


def error_code(payload: Any) -> Any:
    """Extract a stable error code from an HTTP error body, tolerantly."""
    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
        if isinstance(detail, dict) and "code" in detail:
            return detail["code"]
        return detail
    return payload


def assert_no_sensitive_text(*bodies: Any) -> None:
    """SEC-9.2-05/08: none of the fixture/secret sentinels may appear."""
    rendered = " | ".join(str(b) for b in bodies)
    for sentinel in (SECRET_SENTINEL, BASE_URL_SENTINEL):
        assert sentinel not in rendered, f"sensitive sentinel leaked: {sentinel}"


def build_service(**kwargs: Any) -> Any:
    """Construct the Stage 9.2 title service.

    Tries the planned public surface in ``autoedit.title_generator``:

        TitleGenerator(settings=None, llm_client=None, cache_max_entries=None,
                       context_char_budget=None)
        .generate(summary, strategies=..., count=..., variation=...)

    Fails clearly (does not skip) when the implementation surface is absent.
    """
    from autoedit import title_generator as tg

    service_cls = getattr(tg, "TitleGenerator", None)
    if service_cls is None:
        raise AssertionError(
            "autoedit.title_generator.TitleGenerator is required by the "
            "Stage 9.2 test suite (ARCH-9.2-02 / BACKEND-9.2-19)"
        )
    try:
        return service_cls(**kwargs)
    except TypeError:
        # Constructor signature drifted; surface the expected surface.
        raise AssertionError(
            "TitleGenerator must accept kwargs: settings, llm_client, "
            "cache_max_entries, context_char_budget (ARCH-9.2-02/07)"
        ) from None


def mock_service(**kwargs: Any) -> Any:
    """A service pinned to the deterministic mock backend (no network)."""
    from autoedit.config import Settings

    kwargs.setdefault("settings", Settings(TITLE_BACKEND="mock"))
    return build_service(**kwargs)
