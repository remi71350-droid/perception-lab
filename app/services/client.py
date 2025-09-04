from __future__ import annotations

from typing import Protocol, Optional, Dict, Any
import requests


def _pack(
    video_path: str,
    profile: str,
    duration_s: int = 10,
    emit_video: bool = False,
    overlays: Optional[Dict[str, bool]] = None,
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "video_path": video_path,
        "profile": profile,
        "duration_s": duration_s,
        "emit_video": emit_video,
        "overlays": overlays or {},
        "thresholds": thresholds or {},
    }


class Client(Protocol):
    def run_video(
        self,
        video_path: str,
        profile: str,
        duration_s: int = 10,
        emit_video: bool = False,
        overlays: Optional[Dict[str, bool]] = None,
        thresholds: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...

    def run_control(self, action: str) -> Dict[str, Any]:
        ...

    def ab_compare(self, video_path: str) -> Dict[str, Any]:
        ...

    def clear(self) -> Dict[str, Any]:
        ...


class HttpClient:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def run_video(
        self,
        video_path: str,
        profile: str,
        duration_s: int = 10,
        emit_video: bool = False,
        overlays: Optional[Dict[str, bool]] = None,
        thresholds: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base}/run_video",
            json=_pack(video_path, profile, duration_s, emit_video, overlays, thresholds),
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def run_control(self, action: str) -> Dict[str, Any]:
        resp = requests.post(f"{self.base}/run_control", json={"action": action}, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def ab_compare(self, video_path: str) -> Dict[str, Any]:
        resp = requests.post(f"{self.base}/ab_compare", json={"video_path": video_path}, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def clear(self) -> Dict[str, Any]:
        resp = requests.post(f"{self.base}/clear", timeout=10)
        resp.raise_for_status()
        return resp.json()


