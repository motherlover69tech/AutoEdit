from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET


def _ms_to_frames(t_ms: int, fps_num: int, fps_den: int) -> int:
    """Convert a millisecond timeline position to a whole frame index."""
    return round(t_ms * fps_num / (fps_den * 1000))


def _to_rational_seconds(t_ms: int, fps_num: int, fps_den: int) -> str:
    """Convert frame-exact integer ms to a rational seconds string."""
    frames = _ms_to_frames(t_ms, fps_num, fps_den)
    num = frames * fps_den
    return f"{num}/{fps_num}s"


def _span_to_rational(start_ms: int, end_ms: int, fps_num: int, fps_den: int) -> tuple[str, str, int]:
    """Convert a [start_ms, end_ms) span to (offset, duration) rationals.

    Both boundaries are converted to frame indices and the duration is the
    DIFFERENCE of those indices. Converting offset and duration to frames
    independently (round(start) + round(dur) != round(start + dur)) is the
    same rounding bug that once produced one-frame gaps/overlaps between
    adjacent clips in Resolve; deriving durations from shared boundaries
    makes adjacent spans frame-contiguous by construction, even if the
    input CDL is not perfectly frame-snapped.

    Returns (offset_rational, duration_rational, duration_frames).
    """
    start_f = _ms_to_frames(start_ms, fps_num, fps_den)
    end_f = _ms_to_frames(end_ms, fps_num, fps_den)
    dur_f = end_f - start_f
    return (
        f"{start_f * fps_den}/{fps_num}s",
        f"{dur_f * fps_den}/{fps_num}s",
        dur_f,
    )


def _frames_to_rational(frames: int, fps_num: int, fps_den: int) -> str:
    """Convert frame count to rational seconds."""
    return f"{frames * fps_den}/{fps_num}s"


def write_fcpxml(
    cdl: dict,
    project_fps_num: int,
    project_fps_den: int,
    angles: list[dict],
    output_path: Path,
    *,
    mode: str = "multitrack",
    notes: list[dict] | None = None,
) -> Path:
    """Write an FCPXML 1.9 file from a validated CDL.

    Note markers are interspersed directly in the spine at their timeline
    positions. **DaVinci Resolve does not import markers from FCPXML** —
    this is a Resolve limitation. Use Stage 8.3 (OTIO → EDL) to deliver
    markers into Resolve.
    """
    clips = cdl.get("clips", [])

    angle_order = sorted(angles, key=lambda a: a["id"])
    lane_by_angle = {a["id"]: i for i, a in enumerate(angle_order)}

    total_ms = 0
    if clips:
        last = clips[-1]
        total_ms = last["timeline_in_ms"] + last["dur_ms"]
    total_frames = round(total_ms * project_fps_num / (project_fps_den * 1000))

    width = angles[0].get("width", 1920) if angles else 1920
    height = angles[0].get("height", 1080) if angles else 1080

    # Build sorted list of all spine-level items: (timeline_ms, type, data)
    # Then sort and emit in order — markers get placed between clips at their timeline position
    spine_items = []

    if mode == "single":
        for clip in clips:
            spine_items.append((clip["timeline_in_ms"], "clip", {
                "angle_id": clip["angle_id"],
                "src_in_ms": clip["src_in_ms"],
                "dur_ms": clip["dur_ms"],
                "end_ms": clip["timeline_in_ms"] + clip["dur_ms"],
            }))
    else:
        if clips:
            cut_points = sorted({
                0,
                *(clip["timeline_in_ms"] for clip in clips),
                *(clip["timeline_in_ms"] + clip["dur_ms"] for clip in clips),
            })
            for i in range(len(cut_points) - 1):
                w_start, w_end = cut_points[i], cut_points[i + 1]
                w_dur = w_end - w_start
                if w_dur <= 0:
                    continue
                active_angle, src_in = None, 0
                for clip in clips:
                    c_start = clip["timeline_in_ms"]
                    c_end = c_start + clip["dur_ms"]
                    if c_start <= w_start and c_end >= w_end:
                        active_angle = clip["angle_id"]
                        src_in = clip["src_in_ms"] + (w_start - c_start)
                        break
                # Emit one item per angle lane at this window
                for angle in angle_order:
                    aid = angle["id"]
                    lane = lane_by_angle[aid]
                    spine_items.append((w_start, "lane_clip", {
                        "active": active_angle == aid,
                        "angle_id": aid,
                        "src_in_ms": src_in,
                        "dur_ms": w_dur,
                        "end_ms": w_end,
                        "lane": lane,
                    }))

    # Add note markers
    if notes:
        for note in notes:
            t_ms = note["t_ms"]
            if total_ms > 0:
                t_ms = max(0, min(t_ms, total_ms - 1))
            spine_items.append((t_ms, "marker", {
                "author": note.get("author", ""),
                "body": note.get("body", ""),
                "kind": note.get("kind", "note"),
            }))

    # Sort all spine items by timeline position
    spine_items.sort(key=lambda x: x[0])

    # ── Build XML ──────────────────────────────────────────────

    fcpxml = ET.Element("fcpxml", {"version": "1.9"})
    resources = ET.SubElement(fcpxml, "resources")

    ET.SubElement(resources, "format", {
        "id": "r1",
        "frameDuration": _frames_to_rational(1, project_fps_num, project_fps_den),
        "width": str(width),
        "height": str(height),
    })

    # Assets — use base filename so Resolve can relink by name
    used_angle_ids = {}
    for angle in angles:
        aid = angle["id"]
        sp = angle.get("source_path", f"source/{aid}.mp4")
        filename = Path(sp).name
        asset_id = f"a{len(used_angle_ids) + 1}"
        used_angle_ids[aid] = asset_id
        ET.SubElement(resources, "asset", {
            "id": asset_id,
            "name": angle.get("label", aid),
            "format": "r1",
            "start": "0s",
            "duration": "9999s",
            "hasVideo": "1",
            "hasAudio": "1",
            "src": filename,
        })

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", {"name": "AUTOEDIT Export"})
    project = ET.SubElement(event, "project", {"name": "Rough Cut"})
    sequence = ET.SubElement(project, "sequence", {
        "format": "r1",
        "duration": _frames_to_rational(total_frames, project_fps_num, project_fps_den),
    })
    spine = ET.SubElement(sequence, "spine")

    # Emit spine items in timeline order
    for t_ms, item_type, data in spine_items:
        if item_type == "clip":
            offset_r, dur_r, dur_f = _span_to_rational(
                t_ms, data["end_ms"], project_fps_num, project_fps_den
            )
            if dur_f <= 0:
                continue  # span collapsed to zero frames after snapping
            ET.SubElement(spine, "asset-clip", {
                "ref": used_angle_ids[data["angle_id"]],
                "offset": offset_r,
                "start": _to_rational_seconds(data["src_in_ms"], project_fps_num, project_fps_den),
                "duration": dur_r,
            })
        elif item_type == "lane_clip":
            offset_r, dur_r, dur_f = _span_to_rational(
                t_ms, data["end_ms"], project_fps_num, project_fps_den
            )
            if dur_f <= 0:
                continue
            if data["active"]:
                ET.SubElement(spine, "asset-clip", {
                    "ref": used_angle_ids[data["angle_id"]],
                    "offset": offset_r,
                    "start": _to_rational_seconds(data["src_in_ms"], project_fps_num, project_fps_den),
                    "duration": dur_r,
                    "lane": str(data["lane"]),
                })
            else:
                ET.SubElement(spine, "gap", {
                    "offset": offset_r,
                    "start": "0s",
                    "duration": dur_r,
                    "lane": str(data["lane"]),
                })
        elif item_type == "marker":
            value = f"[{data['kind']}] {data['author']}: {data['body']}"
            ET.SubElement(spine, "marker", {
                "start": _to_rational_seconds(t_ms, project_fps_num, project_fps_den),
                "duration": _frames_to_rational(1, project_fps_num, project_fps_den),
                "value": value,
            })

    ET.indent(fcpxml, space="    ")
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(fcpxml, encoding="unicode")
    output_path.write_text(xml_str)
    return output_path
