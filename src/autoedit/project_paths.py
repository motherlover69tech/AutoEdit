from __future__ import annotations

from pathlib import Path
import re

PROJECT_SUBDIRS = (
    "source",
    "proxy",
    "proxy_low",
    "audio",
    "transcript",
    "edit",
    "luts",
)

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def project_root(data_root: str | Path, project_id: str) -> Path:
    """Return the confined root path for a project id.

    Project ids are ULIDs. Rejecting anything else prevents path traversal before later
    media/upload stages start accepting user-controlled names.
    """
    if not _ULID_RE.fullmatch(project_id):
        raise ValueError("project_id must be a 26-character ULID")
    return Path(data_root) / project_id


def create_project_tree(data_root: str | Path, project_id: str) -> Path:
    root = project_root(data_root, project_id)
    root.mkdir(parents=True, exist_ok=True)
    for subdir in PROJECT_SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)
    return root
