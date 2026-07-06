from __future__ import annotations

import math
from pathlib import Path

import pytest

from autoedit.cdl_validator import is_frame_exact, ms_to_frames, validate_cdl
from autoedit.fcpxml_writer import _to_rational_seconds, write_fcpxml


# ── Frame math ───────────────────────────────────────────────

def test_ms_to_frames_23_976():
    assert ms_to_frames(0, 24000, 1001) == 0
    assert ms_to_frames(1001, 24000, 1001) == 24


def test_is_frame_exact_23_976():
    assert is_frame_exact(0, 24000, 1001) is True
    assert is_frame_exact(1001, 24000, 1001) is True
    assert is_frame_exact(500, 24000, 1001) is False


def test_ms_to_frames_25fps():
    assert ms_to_frames(0, 25, 1) == 0
    assert ms_to_frames(40, 25, 1) == 1
    assert ms_to_frames(80, 25, 1) == 2
    assert ms_to_frames(1000, 25, 1) == 25


def test_is_frame_exact_25fps():
    assert is_frame_exact(40, 25, 1) is True
    assert is_frame_exact(41, 25, 1) is False


def test_rational_seconds_25fps():
    assert _to_rational_seconds(0, 25, 1) == "0/25s"
    assert _to_rational_seconds(40, 25, 1) == "1/25s"
    assert _to_rational_seconds(80, 25, 1) == "2/25s"
    assert _to_rational_seconds(1000, 25, 1) == "25/25s"


def test_rational_seconds_23_976():
    assert _to_rational_seconds(1001, 24000, 1001) == "24024/24000s"


# ── Validator: happy path ────────────────────────────────────

def test_valid_cdl_passes():
    cdl = {
        "version": 1,
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 1001},
            {"angle_id": "b", "timeline_in_ms": 1001, "src_in_ms": 0, "dur_ms": 1001},
        ],
    }
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is True


def test_missing_clips_key():
    result = validate_cdl({}, 24000, 1001)
    assert result["valid"] is False
    assert "no clips" in result["error"].lower()


def test_missing_required_fields():
    cdl = {"clips": [{"angle_id": "a"}]}
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False
    assert "missing required fields" in result["error"].lower()


def test_non_integer_times():
    cdl = {"clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 1.5}]}
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False
    assert "dur_ms" in result["error"]


def test_sub_frame_dur_ms():
    cdl = {"clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 500}]}
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False
    assert "frame" in result["error"].lower()


def test_sub_frame_src_in_ms():
    cdl = {"clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 500, "dur_ms": 1001}]}
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False
    assert "src_in_ms" in result["error"]


def test_gap_between_clips():
    cdl = {
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 1001},
            {"angle_id": "b", "timeline_in_ms": 2002, "src_in_ms": 0, "dur_ms": 1001},
        ],
    }
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False
    assert "gap" in result["error"].lower()


def test_overlap_between_clips():
    cdl = {
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 2002},
            {"angle_id": "b", "timeline_in_ms": 1001, "src_in_ms": 0, "dur_ms": 1001},
        ],
    }
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False
    assert "overlap" in result["error"].lower()


def test_out_of_order_clips():
    cdl = {
        "clips": [
            {"angle_id": "b", "timeline_in_ms": 1001, "src_in_ms": 0, "dur_ms": 1001},
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 1001},
        ],
    }
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False
    assert "out of order" in result["error"].lower()


def test_negative_timeline_in_ms():
    cdl = {"clips": [{"angle_id": "a", "timeline_in_ms": -1, "src_in_ms": 0, "dur_ms": 1001}]}
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False


def test_zero_dur_ms():
    cdl = {"clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 0}]}
    result = validate_cdl(cdl, 24000, 1001)
    assert result["valid"] is False


def test_missing_source_file(tmp_path: Path):
    cdl = {
        "clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 1001}],
    }
    result = validate_cdl(cdl, 24000, 1001, source_files={"a": tmp_path / "missing.mp4"})
    assert result["valid"] is False
    assert "not found" in result["error"].lower()


def test_source_file_exists(tmp_path: Path):
    src = tmp_path / "real.mp4"
    src.write_text("fake")
    cdl = {
        "clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 1001}],
    }
    result = validate_cdl(cdl, 24000, 1001, source_files={"a": src})
    assert result["valid"] is True


def test_source_duration_exceeded():
    cdl = {
        "clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 2002, "dur_ms": 1001}],
    }
    result = validate_cdl(cdl, 24000, 1001, source_durations_ms={"a": 2002})
    assert result["valid"] is False
    assert "exceeds" in result["error"].lower()


# ── FCPXML: single-track mode ────────────────────────────────

def test_single_track_writes_valid_xml(tmp_path: Path):
    cdl = {
        "version": 1,
        "clips": [
            {"angle_id": "angle_a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 1001},
            {"angle_id": "angle_b", "timeline_in_ms": 1001, "src_in_ms": 2002, "dur_ms": 2002},
        ],
    }
    angles = [
        {"id": "angle_a", "label": "Presenter", "source_path": "/data/proj/source/a.mp4"},
        {"id": "angle_b", "label": "Guest", "source_path": "/data/proj/source/b.mp4"},
    ]

    out = tmp_path / "single.fcpxml"
    result = write_fcpxml(cdl, 24000, 1001, angles, out, mode="single")
    assert result == out
    assert out.is_file()

    content = out.read_text()
    assert "<fcpxml" in content
    assert 'version="1.9"' in content
    assert "<spine>" in content
    assert '<asset-clip' in content
    assert 'ref="a1"' in content
    assert 'ref="a2"' in content
    # Single-track: no gaps, no lane attrs
    assert "<gap" not in content
    assert "lane" not in content


# ── FCPXML: multi-track mode ─────────────────────────────────

def test_multitrack_writes_stacked_lanes(tmp_path: Path):
    cdl = {
        "version": 1,
        "clips": [
            {"angle_id": "angle_wide", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 3000},
            {"angle_id": "angle_presenter", "timeline_in_ms": 3000, "src_in_ms": 0, "dur_ms": 5000},
            {"angle_id": "angle_wide", "timeline_in_ms": 8000, "src_in_ms": 3080, "dur_ms": 2000},
        ],
    }
    angles = [
        {"id": "angle_presenter", "label": "Presenter", "source_path": "/tmp/p.mp4"},
        {"id": "angle_wide", "label": "Wide", "source_path": "/tmp/w.mp4"},
    ]

    out = tmp_path / "multi.fcpxml"
    write_fcpxml(cdl, 25, 1, angles, out, mode="multitrack")

    content = out.read_text()

    # Has gap elements (inactive angles)
    assert "<gap" in content

    # Has lane attributes
    assert 'lane="0"' in content
    assert 'lane="1"' in content

    # Both angles' assets exist
    assert 'ref="a1"' in content
    assert 'ref="a2"' in content

    # Structure check
    assert "<fcpxml" in content
    assert "<spine>" in content


def test_multitrack_three_angles_all_referenced(tmp_path: Path):
    """Verify all 3 angles appear in the XML."""
    cdl = {
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 2000},
            {"angle_id": "b", "timeline_in_ms": 2000, "src_in_ms": 0, "dur_ms": 2000},
            {"angle_id": "c", "timeline_in_ms": 4000, "src_in_ms": 1000, "dur_ms": 2000},
        ],
    }
    angles = [
        {"id": "a", "label": "A", "source_path": "/tmp/a.mp4"},
        {"id": "b", "label": "B", "source_path": "/tmp/b.mp4"},
        {"id": "c", "label": "C", "source_path": "/tmp/c.mp4"},
    ]

    out = tmp_path / "three.fcpxml"
    write_fcpxml(cdl, 25, 1, angles, out, mode="multitrack")

    content = out.read_text()
    assert 'ref="a1"' in content
    assert 'ref="a2"' in content
    assert 'ref="a3"' in content

    # Three lanes
    assert 'lane="0"' in content
    assert 'lane="1"' in content
    assert 'lane="2"' in content


def test_multitrack_gap_count(tmp_path: Path):
    """Each inactive angle gets a gap element for every CDL window."""
    cdl = {
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 2000},
            {"angle_id": "b", "timeline_in_ms": 2000, "src_in_ms": 0, "dur_ms": 2000},
            {"angle_id": "a", "timeline_in_ms": 4000, "src_in_ms": 2000, "dur_ms": 2000},
        ],
    }
    angles = [
        {"id": "a", "label": "A", "source_path": "/tmp/a.mp4"},
        {"id": "b", "label": "B", "source_path": "/tmp/b.mp4"},
    ]

    out = tmp_path / "gaps.fcpxml"
    write_fcpxml(cdl, 25, 1, angles, out, mode="multitrack")

    content = out.read_text()
    # 3 windows × 2 angles = 6 total elements, 3 gaps (1 per inactive angle per window)
    # Window 0 (a active): b gets gap
    # Window 1 (b active): a gets gap
    # Window 2 (a active): b gets gap
    # = 3 gaps total
    assert content.count("<gap") == 3
    assert content.count("<asset-clip") == 3


def test_multitrack_empty_clips(tmp_path: Path):
    cdl = {"clips": []}
    angles = [{"id": "a", "label": "A", "source_path": "/tmp/a.mp4"}]
    out = tmp_path / "empty.fcpxml"
    result = write_fcpxml(cdl, 24000, 1001, angles, out)
    assert result.is_file()
    assert "<spine />" in out.read_text() or "<spine>" in out.read_text()


# ── FCPXML: notes as markers ─────────────────────────────────

def test_single_track_with_notes(tmp_path: Path):
    cdl = {
        "clips": [
            {"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 3000},
            {"angle_id": "b", "timeline_in_ms": 3000, "src_in_ms": 500, "dur_ms": 5000},
        ],
    }
    angles = [
        {"id": "a", "label": "A", "source_path": "/tmp/a.mp4"},
        {"id": "b", "label": "B", "source_path": "/tmp/b.mp4"},
    ]
    notes = [
        {"t_ms": 1000, "author": "Peter", "body": "Cut here", "kind": "cut_suggestion"},
        {"t_ms": 4000, "author": "Guest", "body": "Nice moment", "kind": "note"},
    ]

    out = tmp_path / "with_notes.fcpxml"
    write_fcpxml(cdl, 25, 1, angles, out, mode="single", notes=notes)

    content = out.read_text()
    assert content.count("<marker") == 2
    assert "Cut here" in content
    assert "Nice moment" in content
    assert "[cut_suggestion] Peter: Cut here" in content
    assert "[note] Guest: Nice moment" in content
    # Markers are interspersed in spine — between asset-clips
    assert "<marker" in content
    # Should be inside spine (before </spine>)
    spine_close = content.index("</spine>")
    spine_open = content.index("<spine>")
    marker_pos = content.index("<marker")
    assert spine_open < marker_pos < spine_close, "markers should be inside spine"


def test_multitrack_with_notes(tmp_path: Path):
    cdl = {
        "clips": [
            {"angle_id": "wide", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 3000},
            {"angle_id": "cu", "timeline_in_ms": 3000, "src_in_ms": 0, "dur_ms": 5000},
            {"angle_id": "wide", "timeline_in_ms": 8000, "src_in_ms": 3100, "dur_ms": 2000},
        ],
    }
    angles = [
        {"id": "cu", "label": "CU", "source_path": "/tmp/cu.mp4"},
        {"id": "wide", "label": "Wide", "source_path": "/tmp/wide.mp4"},
    ]
    notes = [
        {"t_ms": 1500, "author": "P", "body": "Cut at 1.5s", "kind": "cut_suggestion"},
        {"t_ms": 5000, "author": "P", "body": "Good take", "kind": "note"},
        {"t_ms": 9000, "author": "P", "body": "End check", "kind": "note"},
    ]

    out = tmp_path / "multi_notes.fcpxml"
    write_fcpxml(cdl, 25, 1, angles, out, mode="multitrack", notes=notes)

    content = out.read_text()
    # All 3 notes appear
    assert content.count("<marker") == 3
    assert "Cut at 1.5s" in content
    assert "Good take" in content
    assert "End check" in content


def test_fcpxml_includes_file_names(tmp_path: Path):
    cdl = {
        "clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 2002}],
    }
    angles = [{"id": "a", "label": "Cam", "source_path": "/tmp/test.mp4"}]

    out = tmp_path / "export.fcpxml"
    write_fcpxml(cdl, 30000, 1001, angles, out)

    content = out.read_text()
    assert 'src="test.mp4"' in content


def test_notes_empty_list_no_markers(tmp_path: Path):
    cdl = {
        "clips": [{"angle_id": "a", "timeline_in_ms": 0, "src_in_ms": 0, "dur_ms": 2000}],
    }
    angles = [{"id": "a", "label": "A", "source_path": "/tmp/a.mp4"}]

    out = tmp_path / "no_notes.fcpxml"
    write_fcpxml(cdl, 25, 1, angles, out, mode="multitrack", notes=[])

    content = out.read_text()
    assert "<marker" not in content
