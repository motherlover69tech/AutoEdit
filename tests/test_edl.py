from __future__ import annotations

from pathlib import Path

from autoedit.edl_writer import write_edl, _ms_to_timecode


def test_timecode_25fps():
    assert _ms_to_timecode(0, 25, 1) == "00:00:00:00"
    assert _ms_to_timecode(40, 25, 1) == "00:00:00:01"    # 1 frame
    assert _ms_to_timecode(1000, 25, 1) == "00:00:01:00"   # 1 second = 25 frames
    assert _ms_to_timecode(60000, 25, 1) == "00:01:00:00"  # 1 minute
    assert _ms_to_timecode(3600000, 25, 1) == "01:00:00:00"  # 1 hour


def test_timecode_24fps():
    assert _ms_to_timecode(0, 24, 1) == "00:00:00:00"
    assert _ms_to_timecode(1000, 24, 1) == "00:00:01:00"   # ~24 frames at 41.67ms


def test_basic_edl(tmp_path: Path):
    cdl = {
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 3000},
            {"angle_id": "b", "timeline_in_ms": 3000, "src_in_ms": 500, "dur_ms": 5000},
        ],
    }
    angles = [
        {"id": "a", "label": "Wide", "source_path": "/tmp/wide.mp4"},
        {"id": "b", "label": "Presenter", "source_path": "/tmp/presenter.mp4"},
    ]

    out = tmp_path / "test.edl"
    write_edl(cdl, 25, 1, angles, out)

    content = out.read_text()
    assert "TITLE: AUTOEDIT Export" in content
    assert "FCM: NON-DROP FRAME" in content
    assert "001  WIDE" in content
    assert "002  PRESEN" in content  # truncated to 6 chars
    assert "FROM CLIP NAME: wide.mp4" in content
    assert "FROM CLIP NAME: presenter.mp4" in content


def test_edl_with_notes(tmp_path: Path):
    cdl = {
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 3000},
            {"angle_id": "b", "timeline_in_ms": 3000, "src_in_ms": 0, "dur_ms": 5000},
        ],
    }
    angles = [
        {"id": "a", "label": "Wide", "source_path": "/tmp/wide.mp4"},
        {"id": "b", "label": "Presenter", "source_path": "/tmp/presenter.mp4"},
    ]
    notes = [
        {"t_ms": 500, "author": "Peter", "body": "Good establishing", "kind": "note"},
        {"t_ms": 4000, "author": "Guest", "body": "Cut suggestion here", "kind": "cut_suggestion"},
    ]

    out = tmp_path / "with_notes.edl"
    write_edl(cdl, 25, 1, angles, out, notes=notes)

    content = out.read_text()

    # LOC markers present
    assert "* LOC:" in content
    assert "Good establishing" in content
    assert "Cut suggestion here" in content
    assert "[note] Peter: Good establishing" in content
    assert "[cut_suggestion] Guest: Cut suggestion here" in content

    # Note at 500ms: 500 * 25 / 1000 = 12.5 → round to 13 frames
    assert "00:00:00:12" in content  # 500ms → round(12.5 frames) = 12


def test_edl_no_notes(tmp_path: Path):
    cdl = {
        "clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 2000}],
    }
    angles = [{"id": "a", "label": "Cam", "source_path": "/tmp/cam.mp4"}]

    out = tmp_path / "no_notes.edl"
    write_edl(cdl, 25, 1, angles, out)

    content = out.read_text()
    assert "* LOC:" not in content
    assert "FROM CLIP NAME: cam.mp4" in content


def test_edl_empty_clips(tmp_path: Path):
    cdl = {"clips": []}
    angles = [{"id": "a", "label": "A", "source_path": "/tmp/a.mp4"}]

    out = tmp_path / "empty.edl"
    write_edl(cdl, 25, 1, angles, out)

    content = out.read_text()
    assert "TITLE:" in content
    assert "FCM:" in content


def test_edl_multiple_notes_per_clip(tmp_path: Path):
    cdl = {
        "clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 10000}],
    }
    angles = [{"id": "a", "label": "Main", "source_path": "/tmp/main.mp4"}]
    notes = [
        {"t_ms": 2000, "author": "P", "body": "Note 1", "kind": "note"},
        {"t_ms": 5000, "author": "P", "body": "Note 2", "kind": "cut_suggestion"},
        {"t_ms": 8000, "author": "P", "body": "Note 3", "kind": "note"},
    ]

    out = tmp_path / "multi_notes.edl"
    write_edl(cdl, 25, 1, angles, out, notes=notes)

    content = out.read_text()
    assert content.count("* LOC:") == 3


def test_edl_records_timeline_offsets(tmp_path: Path):
    """Verify record timecodes are correct timeline positions."""
    cdl = {
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 2000},
            {"angle_id": "a", "timeline_in_ms": 2000, "src_in_ms": 5000, "dur_ms": 3000},
        ],
    }
    angles = [{"id": "a", "label": "A", "source_path": "/tmp/a.mp4"}]

    out = tmp_path / "offsets.edl"
    write_edl(cdl, 25, 1, angles, out)

    content = out.read_text()
    # Clip 1: rec_in = 00:00:00:00, rec_out = 00:00:02:00 (2000ms = 2s = 50 frames)
    # Clip 2: rec_in = 00:00:02:00, rec_out = 00:00:05:00 (timeline 2000→5000ms)
    assert "00:00:00:00 00:00:02:00" in content
    assert "00:00:02:00 00:00:05:00" in content
