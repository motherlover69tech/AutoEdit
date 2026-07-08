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
