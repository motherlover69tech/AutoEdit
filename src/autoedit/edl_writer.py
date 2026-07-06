from __future__ import annotations

from pathlib import Path


def _ms_to_timecode(t_ms: int, fps_num: int, fps_den: int) -> str:
    """Convert milliseconds to CMX3600 timecode (HH:MM:SS:FF)."""
    total_frames = round(t_ms * fps_num / (fps_den * 1000))
    frames = total_frames % fps_num
    total_seconds = total_frames // fps_num
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def _reel_name(angle_id: str, angle_label: str) -> str:
    """Create a short reel name from angle info (max 8 chars for CMX)."""
    label = angle_label or angle_id
    # Take first 6 chars, uppercase, alphanumeric only
    clean = "".join(c for c in label.upper() if c.isalnum())[:6]
    return clean or "AX"


def write_edl(
    cdl: dict,
    project_fps_num: int,
    project_fps_den: int,
    angles: list[dict],
    output_path: Path,
    *,
    notes: list[dict] | None = None,
    title: str = "AUTOEDIT Export",
) -> Path:
    """Write a CMX 3600 EDL file from a validated CDL.

    FCPXML note markers **are ignored by Resolve**, but EDL `* LOC:` lines
    are imported as timeline locators. This writer generates both clip events
    and marker locators.

    Args:
        cdl: Validated CDL dict with "clips" key.
        project_fps_num/m: FPS.
        angles: List of {id, label, source_path}.
        output_path: Where to write the .edl file.
        notes: Optional list of {t_ms, author, body, kind} for LOC markers.
        title: EDL title line.

    Returns:
        The output path.
    """
    clips = cdl.get("clips", [])
    angle_by_id = {a["id"]: a for a in angles}

    # Sort notes by time for sequential output
    sorted_notes = sorted(notes or [], key=lambda n: n["t_ms"])

    lines = []
    lines.append(f"TITLE: {title}")
    lines.append("FCM: NON-DROP FRAME")
    lines.append("")

    # Map each note to the clip it falls within, for interleaving
    note_map: dict[int, list[dict]] = {}  # clip_index -> [notes]
    for note in sorted_notes:
        t = note["t_ms"]
        for i, clip in enumerate(clips):
            c_start = clip["timeline_in_ms"]
            c_end = c_start + clip["dur_ms"]
            if c_start <= t < c_end:
                note_map.setdefault(i, []).append(note)
                break

    for i, clip in enumerate(clips):
        angle = angle_by_id.get(clip["angle_id"], {})
        reel = _reel_name(clip["angle_id"], angle.get("label", ""))

        src_in = _ms_to_timecode(clip["src_in_ms"], project_fps_num, project_fps_den)
        src_out = _ms_to_timecode(
            clip["src_in_ms"] + clip["dur_ms"], project_fps_num, project_fps_den
        )
        rec_in = _ms_to_timecode(clip["timeline_in_ms"], project_fps_num, project_fps_den)
        rec_out = _ms_to_timecode(
            clip["timeline_in_ms"] + clip["dur_ms"], project_fps_num, project_fps_den
        )

        event_num = i + 1
        lines.append(
            f"{event_num:03d}  {reel:8s} V     C        "
            f"{src_in} {src_out} {rec_in} {rec_out}"
        )

        # Source filename comment
        src_name = Path(angle.get("source_path", f"source/{clip['angle_id']}.mp4")).name
        lines.append(f"* FROM CLIP NAME: {src_name}")

        # Marker LOC lines for this clip
        for note in note_map.get(i, []):
            loc_tc = _ms_to_timecode(note["t_ms"], project_fps_num, project_fps_den)
            value = f"[{note.get('kind', 'note')}] {note.get('author', '')}: {note.get('body', '')}"
            lines.append(f"* LOC: {loc_tc} {value}")

        lines.append("")

    output_path.write_text("\n".join(lines) + "\n")
    return output_path
