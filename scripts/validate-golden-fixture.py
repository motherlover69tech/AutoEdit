#!/usr/bin/env python3
"""Validate a consent-safe golden fixture without inference or deployment side effects."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Keep this validate-only utility runnable directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoedit.ai.golden_fixture import redacted_result, validate_fixture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--validate-only", action="store_true", help="explicitly retain the safe default")
    parser.add_argument("--redacted-summary", type=Path, help="optional named run output for the redacted result")
    args = parser.parse_args()
    root_value = os.environ.get("AUTOEDIT_GOLDEN_MEDIA_ROOT")
    if not root_value:
        result = redacted_result(valid=False, errors=["GOLD_ROOT_NOT_CONFIGURED"])
    else:
        result = validate_fixture(Path(root_value), args.fixture_id)
    output = json.dumps(result, sort_keys=True, separators=(",", ":"))
    print(output)
    if args.redacted_summary:
        if not root_value:
            parser.error("--redacted-summary requires AUTOEDIT_GOLDEN_MEDIA_ROOT")
        root = Path(root_value).resolve(strict=True)
        destination = args.redacted_summary.resolve(strict=False)
        runs_root = (root / "runs").resolve(strict=False)
        if destination != runs_root and runs_root not in destination.parents:
            parser.error("redacted summary must be confined beneath the consent-controlled runs root")
        if destination.exists() and (destination.is_symlink() or destination.stat().st_mode & 0o077):
            parser.error("redacted summary path is not restrictive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        destination.write_text(output + "\n", encoding="utf-8")
        os.chmod(destination, 0o600)
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
