from __future__ import annotations

import os
from pathlib import Path

import pytest


def write(p: Path, text: str = ""):  # helper
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_offline_assets_fail_tmp(tmp_path: Path):
    root = tmp_path / "offline" / "day"
    root.mkdir(parents=True)
    # leave required files missing
    env = {"OFFLINE_ROOT": str(tmp_path / "offline")}
    code = _run_checker(env)
    assert code != 0


def test_offline_assets_pass_tmp(tmp_path: Path):
    offline = tmp_path / "offline"
    for s in ["day", "night", "rain", "tunnel", "snow", "pedestrians"]:
        sdir = offline / s
        sdir.mkdir(parents=True)
        (sdir / "realtime_frame.png").write_bytes(b"\x89PNG\r\n")
        (sdir / "accuracy_frame.png").write_bytes(b"\x89PNG\r\n")
        (sdir / "last_frame.png").write_bytes(b"\x89PNG\r\n")
        write(sdir / "events.jsonl", "{}\n")
    env = {"OFFLINE_ROOT": str(offline)}
    code = _run_checker(env)
    assert code == 0


def _run_checker(env: dict[str, str]) -> int:
    import importlib.util
    import runpy
    import sys
    from types import ModuleType

    script = Path("scripts/check_offline_assets.py").resolve()
    prev = dict(os.environ)
    try:
        os.environ.update(env)
        # Run the script as main and capture exitcode by wrapping main()
        spec = importlib.util.spec_from_file_location("_chk", script)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore[assignment]
        return int(mod.main())  # type: ignore[attr-defined]
    finally:
        os.environ.clear()
        os.environ.update(prev)


