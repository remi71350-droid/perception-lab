from __future__ import annotations

from pathlib import Path, PurePath
import shutil
import time
from typing import Dict, Any, Optional


SCENARIO_MAP: Dict[str, str] = {
    "day": "offline/day",
    "night": "offline/night",
    "rain": "offline/rain",
    "tunnel": "offline/tunnel",
    "pedestrians": "offline/crosswalk",
    "snow": "offline/snow",
}


class OfflineClient:
    def __init__(self) -> None:
        Path("runs/latest").mkdir(parents=True, exist_ok=True)

    def _copy(self, src: Path, dst: Path) -> None:
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)

    def _base(self, video_path: str) -> Path:
        sid = PurePath(video_path).stem
        return Path(SCENARIO_MAP.get(sid, "offline/day"))

    def run_video(
        self,
        video_path: str,
        profile: str,
        duration_s: int = 10,
        emit_video: bool = False,
        overlays: Optional[Dict[str, bool]] = None,
        thresholds: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        base = self._base(video_path)
        out = Path("runs/latest")
        out.mkdir(parents=True, exist_ok=True)
        time.sleep(0.35)  # simulate RTT pacing
        # choose last frame based on profile for subtle difference
        self._copy(base / ("accuracy_frame.png" if profile == "accuracy" else "realtime_frame.png"), out / "last_frame.png")
        self._copy(base / "events.jsonl", out / "events.jsonl")
        if emit_video:
            self._copy(base / "out.mp4", out / "out.mp4")
        return {"ok": True, "last_frame": str(out / "last_frame.png")}

    def run_control(self, action: str) -> Dict[str, Any]:
        time.sleep(0.1)
        return {"ok": True, "action": action}

    def ab_compare(self, video_path: str) -> Dict[str, Any]:
        base = self._base(video_path)
        out = Path("runs/latest")
        out.mkdir(parents=True, exist_ok=True)
        self._copy(base / "realtime_frame.png", out / "realtime_frame.png")
        self._copy(base / "accuracy_frame.png", out / "accuracy_frame.png")
        return {"ok": True}

    def clear(self) -> Dict[str, Any]:
        out = Path("runs/latest")
        if out.exists():
            for p in out.iterdir():
                try:
                    p.unlink()
                except Exception:
                    pass
        return {"ok": True}


