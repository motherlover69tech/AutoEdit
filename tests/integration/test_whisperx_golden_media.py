"""Trusted-host WhisperX fixture acceptance preflight.

This module never downloads media, starts a worker, or writes into a fixture.
The external root is deliberately opt-in; a missing root is a clean skip, while
an explicitly supplied invalid root fails loudly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autoedit.ai.golden_fixture import validate_fixture


@pytest.fixture(scope="module")
def golden_root() -> Path:
    value = os.environ.get("AUTOEDIT_GOLDEN_MEDIA_ROOT")
    if not value:
        pytest.skip("AUTOEDIT_GOLDEN_MEDIA_ROOT is not configured")
    root = Path(value)
    if not root.is_dir():
        pytest.fail("configured golden fixture root is not a directory")
    return root


def test_consent_real_fixture_set_is_complete_and_redacted(golden_root: Path) -> None:
    """Validate all external excerpts without retaining private evidence."""
    fixtures = golden_root / "fixtures"
    if not fixtures.is_dir():
        pytest.fail("configured golden fixture root has no fixtures directory")
    fixture_dirs = sorted(path for path in fixtures.iterdir() if path.is_dir() and not path.is_symlink())
    assert len(fixture_dirs) >= 3, "TEST-AIGPU1-001 requires at least three excerpts"

    results = [validate_fixture(golden_root, path.name) for path in fixture_dirs]
    assert all(result["valid"] for result in results), results
    assert all(result["fixture_class"] == "consent_real" for result in results)
    assert all(result["counts"].get("words", 0) >= 3 for result in results)
    assert all(result["counts"].get("anonymous_clusters", 0) >= 2 for result in results)
    assert all(result["counts"].get("review_windows", 0) >= 8 for result in results)

    # The retained result is intentionally aggregate-only: no source paths,
    # hashes, transcript text, names, runtime IDs, or media-like values.
    encoded = json.dumps(results, sort_keys=True)
    assert str(golden_root) not in encoded
    assert "sha256" not in encoded
    assert "transcript" not in encoded


def test_gate_one_word_selection_is_three_thirds_and_two_clusters(golden_root: Path) -> None:
    """TEST-AIGPU1-002: each accepted package carries the Gate 1 selection shape."""
    fixtures = golden_root / "fixtures"
    fixture_dirs = sorted(path for path in fixtures.iterdir() if path.is_dir() and not path.is_symlink())
    for package in fixture_dirs:
        result = validate_fixture(golden_root, package.name)
        assert result["valid"]
        assert result["counts"]["words"] >= 3
        assert result["counts"]["anonymous_clusters"] >= 2


def test_missing_root_is_not_silently_replaced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """SEC-AIGPU1-001/005: absent configuration cannot fall back to bundled media."""
    monkeypatch.delenv("AUTOEDIT_GOLDEN_MEDIA_ROOT", raising=False)
    result = validate_fixture(tmp_path, "bundled-placeholder")
    assert result == {
        "valid": False,
        "fixture_class": None,
        "errors": ["GOLD_ROOT_NOT_CONFIGURED"],
        "counts": {},
        "schema_version": "1.0",
    }
