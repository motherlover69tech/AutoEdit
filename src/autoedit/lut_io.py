from __future__ import annotations

import re
from pathlib import Path


def parse_cube_header(content: str) -> dict:
    """Parse a .cube LUT file header and validate it.

    Returns:
        dict with keys: title, size, min_values, max_values
    Raises:
        ValueError if the content is not a valid .cube LUT file.
    """
    lines = content.splitlines()
    title = ""
    size = None
    min_vals = [0.0, 0.0, 0.0]
    max_vals = [1.0, 1.0, 1.0]
    data_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("TITLE") or stripped.startswith("BMD_TITLE"):
            title = stripped.partition('"')[2].rpartition('"')[0] or stripped.split(maxsplit=1)[-1].strip('"')
            continue

        if stripped.startswith("LUT_3D_SIZE"):
            parts = stripped.split()
            if len(parts) < 2:
                raise ValueError("Invalid LUT_3D_SIZE line")
            try:
                size = int(parts[1])
            except ValueError:
                raise ValueError(f"Invalid LUT_3D_SIZE value: {parts[1]}")
            if size < 2 or size > 256:
                raise ValueError(f"LUT_3D_SIZE must be between 2 and 256, got {size}")
            continue

        if stripped.startswith("DOMAIN_MIN"):
            parts = stripped.split()
            if len(parts) >= 4:
                min_vals = [float(parts[1]), float(parts[2]), float(parts[3])]
            continue

        if stripped.startswith("DOMAIN_MAX"):
            parts = stripped.split()
            if len(parts) >= 4:
                max_vals = [float(parts[1]), float(parts[2]), float(parts[3])]
            continue

        # First numeric line is the start of the data table
        try:
            float(stripped.split()[0])
            data_start = i
            break
        except (ValueError, IndexError):
            raise ValueError(f"Unexpected line in .cube header: {line!r}")

    if size is None:
        raise ValueError("LUT_3D_SIZE not found in .cube file")

    return {
        "title": title,
        "size": size,
        "min_values": min_vals,
        "max_values": max_vals,
    }


def validate_cube(content: str) -> dict:
    """Validate a .cube LUT file and return its header info.

    Raises ValueError if invalid.
    """
    header = parse_cube_header(content)
    size = header["size"]
    expected_lines = size * size * size

    # Count data lines
    data_lines = 0
    in_data = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if in_data:
                continue
            continue
        if stripped.startswith(("TITLE", "LUT_3D_SIZE", "DOMAIN_MIN", "DOMAIN_MAX")):
            continue
        try:
            parts = stripped.split()
            if len(parts) >= 3:
                float(parts[0])
                float(parts[1])
                float(parts[2])
                data_lines += 1
                in_data = True
        except (ValueError, IndexError):
            if in_data:
                raise ValueError(f"Invalid data line in .cube: {line!r}")

    if data_lines != expected_lines:
        raise ValueError(
            f"Expected {expected_lines} data lines for LUT_3D_SIZE={size}, got {data_lines}"
        )

    return header


def safe_lut_filename(filename: str) -> str:
    """Return a safe filename for a LUT, or raise ValueError."""
    name = Path(filename).name  # Strip any path components
    if name != filename:
        raise ValueError("LUT filename must not contain path separators")
    if not name.lower().endswith(".cube"):
        raise ValueError("LUT file must have .cube extension")
    # Also reject hidden files and empty names
    if name.startswith(".") or name == ".cube":
        raise ValueError("Invalid LUT filename")
    # Only allow safe characters
    if not re.match(r"^[a-zA-Z0-9._-]+$", name):
        raise ValueError("LUT filename contains invalid characters")
    return name


# ── Project LUT state ────────────────────────────────────────

LUT_STATE_FILE = "state.json"


def _json_loads(text: str) -> dict:
    import json
    return json.loads(text)


def _json_dumps(obj: dict) -> str:
    import json
    return json.dumps(obj)


def lut_state_path(project_dir: Path) -> Path:
    return project_dir / "luts" / LUT_STATE_FILE


def read_lut_state(project_dir: Path) -> dict:
    """Read the LUT state file.

    Returns: {"default": str|None, "angle_luts": {angle_id: filename}}
    Migrates legacy {"active": ...} format automatically.
    """
    sp = lut_state_path(project_dir)
    if not sp.is_file():
        return {"default": None, "angle_luts": {}}

    state = _json_loads(sp.read_text())

    # Migrate legacy format
    if "active" in state and "default" not in state:
        state["default"] = state.pop("active")
    if "angle_luts" not in state:
        state["angle_luts"] = {}

    return state


def write_lut_state(project_dir: Path, default: str | None = None,
                    angle_luts: dict[str, str] | None = None,
                    _clear_default: bool = False) -> dict:
    """Write the LUT state file. Merges with existing state."""
    existing = read_lut_state(project_dir)
    if _clear_default or default is not None or (default is None and "default" not in existing):
        existing["default"] = default
    if angle_luts is not None:
        existing["angle_luts"] = angle_luts

    sp = lut_state_path(project_dir)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(_json_dumps(existing))
    return existing


def assign_angle_lut(project_dir: Path, angle_id: str, filename: str) -> dict:
    """Assign a LUT to a specific angle."""
    state = read_lut_state(project_dir)
    state["angle_luts"][angle_id] = filename
    return write_lut_state(project_dir, default=state["default"],
                           angle_luts=state["angle_luts"])


def unassign_angle_lut(project_dir: Path, angle_id: str) -> dict:
    """Remove a LUT assignment for an angle."""
    state = read_lut_state(project_dir)
    state["angle_luts"].pop(angle_id, None)
    return write_lut_state(project_dir, default=state["default"],
                           angle_luts=state["angle_luts"])


def set_default_lut(project_dir: Path, filename: str | None) -> dict:
    """Set or clear the default LUT."""
    return write_lut_state(project_dir, default=filename, _clear_default=(filename is None))


# ── Global LUT library ───────────────────────────────────────

def global_lut_dir(data_root: str | Path) -> Path:
    return Path(data_root) / "luts"


def list_global_luts(data_root: str | Path) -> list[dict]:
    """List LUTs in the global library."""
    gld = global_lut_dir(data_root)
    luts = []
    if gld.is_dir():
        for f in sorted(gld.glob("*.cube")):
            try:
                hdr = parse_cube_header(f.read_text())
                luts.append({"filename": f.name, "title": hdr["title"], "size": hdr["size"]})
            except (ValueError, UnicodeDecodeError):
                luts.append({"filename": f.name, "title": "", "size": 0})
    return luts
