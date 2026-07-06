from __future__ import annotations

from autoedit.title_generator import generate_titles


def test_empty_summary():
    result = generate_titles({"topics": [], "totals": {}})
    assert result["titles"] == []


def test_no_topic_labels():
    result = generate_titles({"topics": [{"label": "", "colour": "#000"}], "totals": {}})
    assert result["titles"] == []


def test_single_topic_single_speaker():
    summary = {
        "topics": [
            {"label": "Climate Policy", "colour": "#3cb44b", "spans": [], "speaker_time_ms": {"Peter": 180000}},
        ],
        "totals": {
            "speaker_time_ms": {"Peter": 180000},
            "talk_overlap_ms": 0,
            "silence_ms": 0,
        },
    }

    result = generate_titles(summary, count=3)
    types = {t["type"] for t in result["titles"]}
    assert types == {"descriptive", "clickbait", "question", "short"}
    assert len(result["titles"]) >= 8  # 4 categories × ~3 each = 12, but may overlap

    # All titles reference the topic; most reference the speaker
    assert all("Climate Policy" in t["text"] for t in result["titles"])
    assert any("Peter" in t["text"] for t in result["titles"])


def test_multi_topic_multi_speaker():
    summary = {
        "topics": [
            {"label": "Budget Discussion", "colour": "#e6194b", "spans": [], "speaker_time_ms": {"Peter": 120000}},
            {"label": "Q&A Session", "colour": "#3cb44b", "spans": [], "speaker_time_ms": {"Guest": 90000}},
        ],
        "totals": {
            "speaker_time_ms": {"Peter": 120000, "Guest": 90000},
            "talk_overlap_ms": 10000,
            "silence_ms": 5000,
        },
    }

    result = generate_titles(summary, count=5)
    assert len(result["titles"]) >= 8

    # Includes both topic references
    texts = [t["text"] for t in result["titles"]]
    assert any("Budget Discussion" in t for t in texts)
    assert any("Q&A Session" in t for t in texts)
    assert any("Peter" in t for t in texts)
    assert any("Guest" in t for t in texts)


def test_includes_duration_when_present():
    summary = {
        "topics": [
            {"label": "Interview", "colour": "#000", "spans": [], "speaker_time_ms": {"Host": 300000}},
        ],
        "totals": {
            "speaker_time_ms": {"Host": 300000},
            "talk_overlap_ms": 0,
            "silence_ms": 0,
        },
    }

    result = generate_titles(summary, count=5)
    # 300000ms = 5 minutes — check any title has duration or just check generation succeeds
    descriptive_texts = [t["text"] for t in result["titles"] if t["type"] == "descriptive"]
    assert len(descriptive_texts) >= 1
    # Should include duration with count=5 (more titles → more likely)
    assert any("min" in t["text"].lower() for t in result["titles"])


def test_no_speakers_still_generates():
    summary = {
        "topics": [
            {"label": "Technology", "colour": "#000", "spans": [], "speaker_time_ms": {}},
        ],
        "totals": {
            "speaker_time_ms": {},
            "talk_overlap_ms": 0,
            "silence_ms": 0,
        },
    }

    result = generate_titles(summary)
    # Should still generate — uses "Speaker" as fallback
    assert len(result["titles"]) >= 8
    assert any("Speaker" in t["text"] for t in result["titles"])


def test_deterministic_same_input():
    """Same input should produce same titles."""
    summary = {
        "topics": [
            {"label": "Climate Policy", "colour": "#3cb44b", "spans": [], "speaker_time_ms": {"Peter": 180000}},
        ],
        "totals": {
            "speaker_time_ms": {"Peter": 180000},
            "talk_overlap_ms": 0,
            "silence_ms": 0,
        },
    }

    r1 = generate_titles(summary)
    r2 = generate_titles(summary)
    assert r1 == r2


def test_all_types_present():
    summary = {
        "topics": [
            {"label": "Topic A", "colour": "#000", "spans": [], "speaker_time_ms": {"Peter": 60000}},
            {"label": "Topic B", "colour": "#000", "spans": [], "speaker_time_ms": {"Guest": 60000}},
        ],
        "totals": {
            "speaker_time_ms": {"Peter": 60000, "Guest": 60000},
            "talk_overlap_ms": 0,
            "silence_ms": 0,
        },
    }

    result = generate_titles(summary)
    types = {t["type"] for t in result["titles"]}
    assert types == {"descriptive", "clickbait", "question", "short"}


def test_count_parameter():
    summary = {
        "topics": [
            {"label": "X", "colour": "#000", "spans": [], "speaker_time_ms": {"A": 60000}},
        ],
        "totals": {"speaker_time_ms": {"A": 60000}, "talk_overlap_ms": 0, "silence_ms": 0},
    }

    result = generate_titles(summary, count=1)
    types = {t["type"] for t in result["titles"]}
    # 4 categories × 1 = 4 titles
    assert len(result["titles"]) == 4
    assert types == {"descriptive", "clickbait", "question", "short"}
