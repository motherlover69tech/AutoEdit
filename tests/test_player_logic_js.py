from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_player_logic_mjs() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; player logic mjs tests skipped")

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "tests/player_logic.test.mjs"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
