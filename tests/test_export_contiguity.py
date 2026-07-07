"""Property tests: no gaps or overlaps anywhere in the export chain.

Guards against the rounding-bug class where positions and durations are
converted to frames independently (round(a) + round(b) != round(a + b)),
which historically produced one-frame gaps/overlaps between adjacent clips
in exported timelines. Exercises random activity timelines at 23.976, 25,
and 29.97 fps through generate_cdl -> validate_cdl -> FCPXML/EDL writers
and asserts frame-level contiguity at every layer.
"""
from __future__ import annotations

import random
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from autoedit.cdl_validator import validate_cdl
from autoedit.cut_engine import generate_cdl
from autoedit.edl_writer import write_edl
from autoedit.fcpxml_writer import write_fcpxml

FPS_CASES = [(24000, 1001), (25, 1), (30000, 1001)]

ANGLES = [
    {"id": "A" * 26, "label": "left", "source_path": "source/left.mp4"},
    {"id": "B" * 26, "label": "right", "source_path": "source/right.mp4"},
    {"id": "W" * 26, "label": "wide", "source_path": "source/wide.mp4"},
]
SPEAKER_TO_ANGLE = {"presenter": "A" * 26, "interviewee": "B" * 26}
# Non-positive offsets, mirroring the app's rebased sync offsets, so
# src_in_ms = timeline_in - offset never goes negative on the first clip.
SYNC_OFFSETS = {"A" * 26: 0, "B" * 26: -120, "W" * 26: -80}


def _random_activity_timeline(rng: random.Random, total_ms: int = 120_000) -> list[dict]:
    """Random alternating speech/overlap/silence segments with messy durations."""
    timeline = []
    t = 0
    states = [["presenter"], ["interviewee"], ["presenter", "interviewee"], []]
    while t < total_ms:
        dur = rng.randint(37, 6113)  # deliberately not frame-aligned
        seg_end = min(t + dur, total_ms)
        timeline.append({
            "start_ms": t,
            "end_ms": seg_end,
            "active": rng.choice(states),
        })
        t = seg_end
    return timeline


def _assert_cdl_contiguous(cdl: dict, fps_num: int, fps_den: int) -> None:
    result = validate_cdl(cdl, fps_num, fps_den)
    assert result["valid"], result.get("error")


def _assert_fcpxml_contiguous(path: Path, fps_num: int, fps_den: int) -> None:
    """Every lane's asset-clips/gaps must tile with no frame gaps or overlaps."""
    tree = ET.parse(path)
    per_lane: dict[str, list[tuple[int, int]]] = {}
    for el in tree.iter():
        if el.tag not in ("asset-clip", "gap"):
            continue
        offset = el.get("offset")
        duration = el.get("duration")
        if offset is None or duration is None:
            continue
        lane = el.get("lane", "spine")

        def rational_frames(value: str) -> int:
            if value == "0s":
                return 0
            m = re.fullmatch(r"(\d+)/(\d+)s", value)
            assert m, f"unexpected rational time {value!r}"
            num, den = int(m.group(1)), int(m.group(2))
            # num/den seconds -> frames: (num/den) * (fps_num/fps_den)
            frames_num = num * fps_num
            frames_den = den * fps_den
            assert frames_num % frames_den == 0, f"{value!r} is not frame-aligned"
            return frames_num // frames_den

        start_f = rational_frames(offset)
        dur_f = rational_frames(duration)
        assert dur_f > 0, "zero/negative-duration element emitted"
        per_lane.setdefault(lane, []).append((start_f, start_f + dur_f))

    assert per_lane, "no clips emitted"
    for lane, spans in per_lane.items():
        spans.sort()
        for (s1, e1), (s2, _e2) in zip(spans, spans[1:]):
            assert e1 == s2, (
                f"lane {lane}: frame discontinuity — clip ends at frame {e1}, "
                f"next starts at frame {s2} ({'gap' if s2 > e1 else 'overlap'})"
            )


_TC_RE = re.compile(
    r"^\d{3}\s+\S+\s+V\s+C\s+"
    r"(\d\d):(\d\d):(\d\d):(\d\d) (\d\d):(\d\d):(\d\d):(\d\d) "
    r"(\d\d):(\d\d):(\d\d):(\d\d) (\d\d):(\d\d):(\d\d):(\d\d)$"
)


def _assert_edl_contiguous(path: Path, fps_num: int, fps_den: int) -> None:
    """Record timecodes must be contiguous: rec_out(i) == rec_in(i+1)."""
    nominal_fps = round(fps_num / fps_den)

    def tc_frames(h: str, m: str, s: str, f: str) -> int:
        return ((int(h) * 60 + int(m)) * 60 + int(s)) * nominal_fps + int(f)

    events = []
    for line in path.read_text().splitlines():
        match = _TC_RE.match(line.strip())
        if match:
            g = match.groups()
            rec_in = tc_frames(*g[8:12])
            rec_out = tc_frames(*g[12:16])
            assert rec_out > rec_in, f"non-positive event duration: {line!r}"
            events.append((rec_in, rec_out))

    assert events, "no EDL events parsed"
    for (r_in1, r_out1), (r_in2, _r_out2) in zip(events, events[1:]):
        assert r_out1 == r_in2, (
            f"EDL record discontinuity: event ends {r_out1}, next starts {r_in2} "
            f"({'gap' if r_in2 > r_out1 else 'overlap'})"
        )


@pytest.mark.parametrize("fps_num,fps_den", FPS_CASES)
@pytest.mark.parametrize("seed", range(8))
def test_export_chain_has_no_gaps_or_overlaps(tmp_path, fps_num, fps_den, seed):
    rng = random.Random(seed)
    timeline = _random_activity_timeline(rng)

    cdl = generate_cdl(
        timeline,
        SPEAKER_TO_ANGLE,
        SYNC_OFFSETS,
        wide_angle_id="W" * 26,
        fps_num=fps_num,
        fps_den=fps_den,
        params={"min_shot_ms": rng.choice([250, 800]),
                "wide_interval_ms": rng.choice([0, 15000])},
    )
    if not cdl["clips"]:
        pytest.skip("random timeline produced no clips")

    _assert_cdl_contiguous(cdl, fps_num, fps_den)

    fcp_path = tmp_path / "out.fcpxml"
    write_fcpxml(cdl, fps_num, fps_den, ANGLES, fcp_path, mode="multitrack")
    _assert_fcpxml_contiguous(fcp_path, fps_num, fps_den)

    fcp_single = tmp_path / "out_single.fcpxml"
    write_fcpxml(cdl, fps_num, fps_den, ANGLES, fcp_single, mode="single")
    _assert_fcpxml_contiguous(fcp_single, fps_num, fps_den)

    edl_path = tmp_path / "out.edl"
    write_edl(cdl, fps_num, fps_den, ANGLES, edl_path)
    _assert_edl_contiguous(edl_path, fps_num, fps_den)


@pytest.mark.parametrize("fps_num,fps_den", FPS_CASES)
def test_unsnapped_cdl_still_exports_contiguously(tmp_path, fps_num, fps_den):
    """Even a CDL that skipped frame snapping must not produce gaps.

    The writers derive durations from shared boundaries, so contiguous-in-ms
    input yields contiguous-in-frames output regardless of snapping.
    """
    clips = []
    t = 0
    rng = random.Random(99)
    for _ in range(40):
        dur = rng.randint(300, 4000)  # arbitrary, unsnapped ms
        clips.append({
            "angle_id": rng.choice(["A" * 26, "B" * 26, "W" * 26]),
            "timeline_in_ms": t,
            "src_in_ms": t + rng.randint(0, 100),
            "dur_ms": dur,
            "reason": "test",
        })
        t += dur
    cdl = {
        "version": 1, "project_id": "", "fps": {"num": fps_num, "den": fps_den},
        "audio": {"channels": []}, "clips": clips, "luts": {"active": None},
    }

    fcp_path = tmp_path / "unsnapped.fcpxml"
    write_fcpxml(cdl, fps_num, fps_den, ANGLES, fcp_path, mode="multitrack")
    _assert_fcpxml_contiguous(fcp_path, fps_num, fps_den)

    edl_path = tmp_path / "unsnapped.edl"
    write_edl(cdl, fps_num, fps_den, ANGLES, edl_path)
    _assert_edl_contiguous(edl_path, fps_num, fps_den)
