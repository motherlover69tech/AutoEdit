from __future__ import annotations

from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1] / "src" / "autoedit" / "web"


def test_ingest_ui_separates_camera_sources_from_speaker_channels() -> None:
    app_html = (WEB_DIR / "app.html").read_text()
    app_js = (WEB_DIR / "app.js").read_text()

    assert "camera sources, not speaker labels" in app_html
    assert "Speaker heard on this channel" in app_js
    assert "Camera source ≠ speaker" in app_js
    assert "placeholder=\"presenter or interviewee\"" in app_js


def test_ingest_ui_does_not_default_cam_left_audio_to_presenter() -> None:
    app_js = (WEB_DIR / "app.js").read_text()

    assert "angle.role === 'cam_left' && ch < 2" not in app_js
    assert "mapped ? 'checked' : ''" in app_js
    assert "mapped?.speaker_label || (ch === 0 ? 'presenter' : 'interviewee')" not in app_js


def test_ingest_ui_shows_persistent_probe_results() -> None:
    app_js = (WEB_DIR / "app.js").read_text()

    assert "state.assets.probes" in app_js
    assert "probeSummaryHtml(angle)" in app_js
    assert "audioStreamSummary(result)" in app_js


def test_phase6_speaker_confirmation_panel_is_bounded_accessible_and_non_destructive() -> None:
    app_html = (WEB_DIR / "app.html").read_text()
    app_js = (WEB_DIR / "app.js").read_text()
    mapping_logic = (WEB_DIR / "speaker_mapping_logic.js").read_text()
    assert 'id="speakerConfirmationPanel"' in app_html
    assert 'aria-live="polite"' in app_html
    assert "useVadBaselineBtn" in app_html and "regenerateWhisperxBtn" in app_html
    assert "Creates a new candidate cut" in app_html or "candidate cut" in app_html
    assert "current cut is unchanged" in app_html
    assert "does not change audio sync" in app_html
    assert 'preload="none"' in app_js
    assert "start_ms" in app_js and "end_ms" in app_js
    for status in ("Confirmed", "Suggested", "Needs confirmation", "Stale"):
        assert status in app_js or status in mapping_logic
    assert "badge" in app_js and "badge ${badge.tone}" in app_js
    assert "sync-nudge" not in app_js.lower()
    assert "per-cut" not in app_js.lower()
