from __future__ import annotations

from fastapi.testclient import TestClient
from app.services.api import app


client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_health_providers(monkeypatch) -> None:
    monkeypatch.setenv("REPLICATE_API_TOKEN", "x")
    monkeypatch.setenv("HF_API_TOKEN", "y")
    monkeypatch.setenv("HF_SEG_ENDPOINT", "https://example.com/seg")
    r = client.get("/health/providers")
    assert r.status_code == 200
    js = r.json()
    assert js["providers"]["replicate_token"] is True
    assert js["providers"]["hf_api_token"] is True
    assert js["providers"]["hf_seg_endpoint"] is True


def test_ab_compare_happy_path(tmp_path, monkeypatch) -> None:
    # Create a tiny synthetic video
    import cv2
    import numpy as np
    vid = str(tmp_path / "tiny.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(vid, fourcc, 5.0, (64, 48))
    for _ in range(6):
        out.write(np.zeros((48, 64, 3), dtype=np.uint8))
    out.release()
    r = client.post("/ab_compare", json={"video_path": vid})
    assert r.status_code == 200
    assert r.json().get("ok") is True
