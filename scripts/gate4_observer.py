#!/usr/bin/env python3
"""Validate an authenticated, already-observed GATE-4 evidence bundle.

This CLI performs file reads and deterministic validation only. It has no
command runner, Docker client, network client, workload submission, cleanup, or
production mutation capability.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from autoedit.ops.gate4_observer import (
    Gate4ObservationError,
    evaluate_gate4_observations,
)


def _json_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Gate4ObservationError(f"{path.name} must contain one JSON object")
    return value


def _ndjson_objects(path: Path) -> list[dict]:
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise Gate4ObservationError(
                f"{path.name} line {line_number} must contain one JSON object"
            )
        result.append(value)
    if not result:
        raise Gate4ObservationError("observation stream is empty")
    return result


def _observation_key() -> bytes:
    encoded = os.environ.get("GATE4_OBSERVATION_KEY_HEX", "")
    try:
        key = bytes.fromhex(encoded)
    except ValueError as exc:
        raise Gate4ObservationError("observation key must be hex encoded") from exc
    if len(key) < 32:
        raise Gate4ObservationError(
            "GATE4_OBSERVATION_KEY_HEX must contain an external 32-byte key"
        )
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only AUTOEDIT GATE-4 observation validator"
    )
    parser.add_argument("--compose-json", type=Path, required=True)
    parser.add_argument("--events-ndjson", type=Path, required=True)
    parser.add_argument("--metadata-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)

    try:
        result = evaluate_gate4_observations(
            _json_object(args.compose_json),
            _ndjson_objects(args.events_ndjson),
            _json_object(args.metadata_json),
            observation_key=_observation_key(),
        )
    except (OSError, json.JSONDecodeError, Gate4ObservationError) as exc:
        print(
            json.dumps({"verdict": "FAIL", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2

    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output_json is not None:
        args.output_json.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
