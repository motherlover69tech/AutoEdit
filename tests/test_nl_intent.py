from __future__ import annotations

import pytest
from autoedit.nl_intent import parse_sub_edit_intent, _fuzzy_match_topics


TOPICS = ["Introduction", "Budget Discussion", "Q&A Session", "Climate Policy", "Closing Remarks", "Guest Interview"]


# ── Fuzzy matching ────────────────────────────────────────────

def test_fuzzy_exact_match():
    result = _fuzzy_match_topics("budget", TOPICS)
    assert "Budget Discussion" in result


def test_fuzzy_substring():
    result = _fuzzy_match_topics("climate", TOPICS)
    assert "Climate Policy" in result


def test_fuzzy_partial_word():
    result = _fuzzy_match_topics("intro", TOPICS)
    assert "Introduction" in result


def test_fuzzy_no_match():
    result = _fuzzy_match_topics("xyzzy_not_a_topic", TOPICS)
    assert result == []


def test_fuzzy_multi_word():
    result = _fuzzy_match_topics("guest interview", TOPICS)
    assert "Guest Interview" in result


# ── Intent: by_topics ─────────────────────────────────────────

def test_about_topic():
    result = parse_sub_edit_intent("about the budget discussion", TOPICS)
    assert result["confident"] is True
    assert result["params"]["mode"] == "by_topics"
    assert "Budget Discussion" in result["params"]["topic_labels"]


def test_make_cut_about():
    result = parse_sub_edit_intent("make me a cut about climate policy", TOPICS)
    assert result["confident"] is True
    assert result["params"]["mode"] == "by_topics"
    assert "Climate Policy" in result["params"]["topic_labels"]


def test_one_minute_about():
    result = parse_sub_edit_intent("one minute about the Q&A session", TOPICS)
    assert result["confident"] is True
    assert result["params"]["mode"] == "by_topics"
    assert "Q&A Session" in result["params"]["topic_labels"]
    assert result["params"]["target_duration_secs"] == 60


def test_90_seconds_about():
    result = parse_sub_edit_intent("give me 90 seconds on guest interview", TOPICS)
    assert result["confident"] is True
    assert result["params"]["target_duration_secs"] == 90
    assert "Guest Interview" in result["params"]["topic_labels"]


def test_two_minutes_about():
    result = parse_sub_edit_intent("I want a 2 minute clip about closing remarks", TOPICS)
    assert result["confident"] is True
    assert result["params"]["target_duration_secs"] == 120
    assert "Closing Remarks" in result["params"]["topic_labels"]


# ── Intent: minus_topics ──────────────────────────────────────

def test_everything_except():
    result = parse_sub_edit_intent("everything except the introduction", TOPICS)
    assert result["confident"] is True
    assert result["params"]["mode"] == "minus_topics"
    assert "Introduction" in result["params"]["exclude_labels"]


def test_minus_topic():
    result = parse_sub_edit_intent("minus the closing remarks", TOPICS)
    assert result["confident"] is True
    assert result["params"]["mode"] == "minus_topics"
    assert "Closing Remarks" in result["params"]["exclude_labels"]


def test_without_topic():
    result = parse_sub_edit_intent("full edit without Q&A session", TOPICS)
    assert result["confident"] is True
    assert result["params"]["mode"] == "minus_topics"


def test_skip_topic():
    result = parse_sub_edit_intent("skip the guest interview", TOPICS)
    assert result["confident"] is True
    assert result["params"]["mode"] == "minus_topics"
    assert "Guest Interview" in result["params"]["exclude_labels"]


# ── Intent: custom_ranges ─────────────────────────────────────

def test_time_range():
    result = parse_sub_edit_intent("from 12:00 to 14:00", TOPICS)
    assert result["confident"] is True
    assert result["params"]["mode"] == "custom_ranges"
    assert result["params"]["ranges"][0]["start_ms"] == 12 * 60 * 60 * 1000
    assert result["params"]["ranges"][0]["end_ms"] == 14 * 60 * 60 * 1000


def test_time_range_with_seconds():
    result = parse_sub_edit_intent("clip from 1:30:00 to 1:45:00", TOPICS)
    assert result["confident"] is True
    assert result["params"]["ranges"][0]["start_ms"] == (3600 + 1800) * 1000
    assert result["params"]["ranges"][0]["end_ms"] == (3600 + 2700) * 1000


# ── Intent: ambiguous / no match ──────────────────────────────

def test_empty_prompt():
    result = parse_sub_edit_intent("", TOPICS)
    assert result["confident"] is False


def test_no_matching_topics():
    result = parse_sub_edit_intent("cut about the space program funding", TOPICS)
    assert result["confident"] is False
    assert "topics matched" in result["reason"].lower() or "no topics" in result["reason"].lower()


def test_vague_prompt():
    result = parse_sub_edit_intent("make it better", TOPICS)
    assert result["confident"] is False


# ── Edge cases ────────────────────────────────────────────────

def test_case_insensitive():
    result = parse_sub_edit_intent("ABOUT THE BUDGET DISCUSSION", TOPICS)
    assert result["confident"] is True
    assert "Budget Discussion" in result["params"]["topic_labels"]


def test_extra_whitespace():
    result = parse_sub_edit_intent("   about   the   introduction   ", TOPICS)
    assert result["confident"] is True
    assert "Introduction" in result["params"]["topic_labels"]
