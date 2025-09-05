#!/usr/bin/env python3
"""
CI check: ensure offline assets exist for each configured scenario.

Required files per scenario directory under offline/<scenario>/:
- realtime_frame.png
- accuracy_frame.png
- last_frame.png
- events.jsonl

Optional (not required to pass):
- out.mp4
- report.pdf

Exit non-zero if any required file is missing. Prints a concise report.
"""
from __future__ import annotations

import sys
from pathlib import Path
import os


SCENARIOS = [
    "day",
    "night",
    "rain",
    "tunnel",
    "snow",
    "pedestrians",
]

REQUIRED = [
    "realtime_frame.png",
    "accuracy_frame.png",
    "last_frame.png",
    "events.jsonl",
]


def main() -> int:
    # Allow CI/tests to override the project root via OFFLINE_ROOT
    override = os.getenv("OFFLINE_ROOT")
    if override:
        offline_root = Path(override)
    else:
        root = Path(__file__).resolve().parents[1]
        offline_root = root / "offline"
    missing: list[str] = []

    for scenario in SCENARIOS:
        sdir = offline_root / scenario
        if not sdir.exists():
            missing.append(f"offline/{scenario}/ (directory missing)")
            continue
        for fname in REQUIRED:
            f = sdir / fname
            if not f.exists():
                missing.append(f"offline/{scenario}/{fname}")

    if missing:
        print("Offline asset check FAILED. Missing:")
        for m in missing:
            print(f" - {m}")
        print("\nGenerate placeholders with: python tools/make_offline_assets.py")
        return 1

    print("Offline asset check PASSED for scenarios:", ", ".join(SCENARIOS))
    return 0


if __name__ == "__main__":
    sys.exit(main())


