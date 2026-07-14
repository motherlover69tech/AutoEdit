"""Tests for the temporal angle-resolution rules in the cut engine.

Covers the two real-world failure modes: "wide the whole time" (cross-mic
bleed makes every segment look like an overlap) and "switches too much"
(backchannel, brief interruptions, and rapid exchanges producing a cut on
every raw VAD edge).
"""
from __future__ import annotations

from autoedit.cut_engine import generate_cdl

MAP = {"presenter": "cam_p", "interviewee": "cam_i"}
OFFSETS = {"cam_p": 0, "cam_i": 0, "wide": 0}


def _cdl(timeline, **params):
    return generate_cdl(
        timeline, MAP, OFFSETS,
        wide_angle_id="wide", fps_num=25, fps_den=1,
        params=params or None,
    )


def _shots(cdl):
    return [(c["angle_id"], c["dur_ms"]) for c in cdl["clips"]]


def _angles(cdl):
    return [c["angle_id"] for c in cdl["clips"]]


def _visual_shots(cdl):
    """Collapse adjacent reason segments that do not change the camera."""
    shots = []
    for clip in cdl["clips"]:
        if shots and shots[-1][0] == clip["angle_id"]:
            shots[-1] = (shots[-1][0], shots[-1][1] + clip["dur_ms"])
        else:
            shots.append((clip["angle_id"], clip["dur_ms"]))
    return shots


# ── Dominance: cross-mic bleed must not read as overlap ───────────────

def test_bleed_resolves_to_dominant_speaker():
    """Both channels 'active' the whole time, but presenter is 14 dB louder:
    this is bleed, and the shot must be the presenter cam, not wide."""
    timeline = [{
        "start_ms": 0, "end_ms": 10000,
        "active": ["interviewee", "presenter"],
        "levels": {"presenter": -18.0, "interviewee": -32.0},
    }]
    cdl = _cdl(timeline)
    assert _angles(cdl) == ["cam_p"]
    assert cdl["clips"][0]["reason"] == "dominance:presenter"
    assert cdl["clips"][0]["reason_code"] == "speaking"


def test_bleed_heavy_conversation_is_not_all_wide():
    """The 'wide the whole time' failure: every segment shows both active
    because of bleed, but levels identify the true speaker per segment."""
    timeline = [
        {"start_ms": 0, "end_ms": 6000, "active": ["interviewee", "presenter"],
         "levels": {"presenter": -20.0, "interviewee": -34.0}},
        {"start_ms": 6000, "end_ms": 12000, "active": ["interviewee", "presenter"],
         "levels": {"presenter": -35.0, "interviewee": -19.0}},
        {"start_ms": 12000, "end_ms": 18000, "active": ["interviewee", "presenter"],
         "levels": {"presenter": -21.0, "interviewee": -33.0}},
    ]
    cdl = _cdl(timeline)
    assert _angles(cdl) == ["cam_p", "cam_i", "cam_p"]
    assert "wide" not in _angles(cdl)


def test_genuine_overlap_close_levels_goes_wide():
    """Levels within dominance_db = genuinely simultaneous speech → wide."""
    timeline = [
        {"start_ms": 0, "end_ms": 4000, "active": ["presenter"]},
        {"start_ms": 4000, "end_ms": 6000, "active": ["interviewee", "presenter"],
         "levels": {"presenter": -22.0, "interviewee": -25.0}},
        {"start_ms": 6000, "end_ms": 10000, "active": ["interviewee"]},
    ]
    cdl = _cdl(timeline)
    assert _angles(cdl) == ["cam_p", "wide", "cam_i"]


def test_no_levels_present_falls_back_to_overlap():
    """Without level data (older activity.json), dominance cannot apply and
    a two-active segment is treated as overlap, as before."""
    timeline = [{"start_ms": 0, "end_ms": 3000, "active": ["interviewee", "presenter"]}]
    cdl = _cdl(timeline)
    assert _angles(cdl) == ["wide"]


# ── Short-overlap absorption ──────────────────────────────────────────

def test_brief_overlap_does_not_flash_wide():
    """A 400 ms overlap at a turn boundary (VAD hangover bridging the
    handover) must not produce a wide flash between the two speaker shots."""
    timeline = [
        {"start_ms": 0, "end_ms": 5000, "active": ["presenter"]},
        {"start_ms": 5000, "end_ms": 5400, "active": ["interviewee", "presenter"],
         "levels": {"presenter": -22.0, "interviewee": -23.0}},
        {"start_ms": 5400, "end_ms": 10000, "active": ["interviewee"]},
    ]
    cdl = _cdl(timeline)
    assert _visual_shots(cdl) == [("cam_p", 5400), ("cam_i", 4600)]
    # Presenter holds the frame through the handover overlap.
    assert [clip["reason_code"] for clip in cdl["clips"][:2]] == [
        "speaking", "short_crosstalk_hold",
    ]


def test_sustained_overlap_still_goes_wide():
    timeline = [
        {"start_ms": 0, "end_ms": 5000, "active": ["presenter"]},
        {"start_ms": 5000, "end_ms": 7500, "active": ["interviewee", "presenter"],
         "levels": {"presenter": -22.0, "interviewee": -23.0}},
        {"start_ms": 7500, "end_ms": 12000, "active": ["interviewee"]},
    ]
    cdl = _cdl(timeline)
    assert _angles(cdl) == ["cam_p", "wide", "cam_i"]


# ── Interjection suppression ──────────────────────────────────────────

def test_backchannel_does_not_steal_the_shot():
    """'mm-hm' (800 ms solo) inside the presenter's turn stays on the
    presenter cam. Previously: three clips and two pointless cuts."""
    timeline = [
        {"start_ms": 0, "end_ms": 6000, "active": ["presenter"]},
        {"start_ms": 6000, "end_ms": 6800, "active": ["interviewee"]},
        {"start_ms": 6800, "end_ms": 12000, "active": ["presenter"]},
    ]
    cdl = _cdl(timeline)
    assert _visual_shots(cdl) == [("cam_p", 12000)]
    assert [clip["reason_code"] for clip in cdl["clips"]] == [
        "speaking", "brief_interjection_hold", "speaking",
    ]


def test_substantial_reply_does_cut():
    """A 3 s remark is a real turn, not backchannel — it gets the shot."""
    timeline = [
        {"start_ms": 0, "end_ms": 6000, "active": ["presenter"]},
        {"start_ms": 6000, "end_ms": 9000, "active": ["interviewee"]},
        {"start_ms": 9000, "end_ms": 15000, "active": ["presenter"]},
    ]
    cdl = _cdl(timeline)
    assert _angles(cdl) == ["cam_p", "cam_i", "cam_p"]


# ── Rapid exchange → wide ─────────────────────────────────────────────

def test_rapid_exchange_holds_wide():
    """Quick back-and-forth (turns every ~1.5-2 s): the middle of the
    exchange goes wide instead of ping-ponging singles. Opening speaker
    keeps the lead-in, closing speaker keeps the tail."""
    timeline = [
        {"start_ms": 0, "end_ms": 8000, "active": ["presenter"]},
        {"start_ms": 8000, "end_ms": 9800, "active": ["interviewee"]},
        {"start_ms": 9800, "end_ms": 11500, "active": ["presenter"]},
        {"start_ms": 11500, "end_ms": 13400, "active": ["interviewee"]},
        {"start_ms": 13400, "end_ms": 22000, "active": ["presenter"]},
    ]
    cdl = _cdl(timeline)
    angles = _angles(cdl)
    assert angles[0] == "cam_p" and angles[-1] == "cam_p"
    assert "wide" in angles
    # No single-speaker ping-pong inside the exchange window.
    assert angles.count("cam_i") == 0


def test_normal_paced_turns_do_not_trigger_exchange():
    """Turns 6-8 s apart are ordinary conversation — straight cuts."""
    timeline = [
        {"start_ms": 0, "end_ms": 7000, "active": ["presenter"]},
        {"start_ms": 7000, "end_ms": 14000, "active": ["interviewee"]},
        {"start_ms": 14000, "end_ms": 21000, "active": ["presenter"]},
        {"start_ms": 21000, "end_ms": 28000, "active": ["interviewee"]},
    ]
    cdl = _cdl(timeline)
    assert _angles(cdl) == ["cam_p", "cam_i", "cam_p", "cam_i"]
    assert "wide" not in _angles(cdl)


# ── Legacy behaviour is recoverable ───────────────────────────────────

def test_zeroed_params_reproduce_instantaneous_behaviour():
    legacy = dict(dominance_db=0, overlap_min_ms=0,
                  interject_max_ms=0, exchange_min_turns=0)
    timeline = [
        {"start_ms": 0, "end_ms": 5000, "active": ["presenter"]},
        {"start_ms": 5000, "end_ms": 5400, "active": ["interviewee", "presenter"],
         "levels": {"presenter": -20.0, "interviewee": -35.0}},
        {"start_ms": 5400, "end_ms": 6200, "active": ["interviewee"]},
        {"start_ms": 6200, "end_ms": 12000, "active": ["presenter"]},
    ]
    cdl = _cdl(timeline, **legacy)
    # Old behaviour: wide flash on the overlap, cut for the interjection.
    assert _angles(cdl) == ["cam_p", "wide", "cam_i", "cam_p"]
