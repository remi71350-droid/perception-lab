from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List

import requests


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    cls: str


class ReplicateDetector:
    """Minimal client wrapper. Replace with official SDK if desired."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.token = os.getenv("REPLICATE_API_TOKEN", "")

    def infer(self, image_b64: str) -> List[Detection]:
        if not self.token:
            return []
        headers = {"Authorization": f"Token {self.token}", "Content-Type": "application/json"}
        url = "https://api.replicate.com/v1/predictions"
        version = self.model
        payload: Dict[str, Any] = {"version": version, "input": {"image": image_b64}}
        # Simple retry with backoff
        backoffs = [0.5, 1.0, 2.0]
        last_exc: Exception | None = None
        for delay in backoffs:
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                if resp.status_code in (429, 500, 502, 503, 504):
                    import time as _t
                    _t.sleep(delay)
                    continue
                if not resp.ok:
                    return []
                data = resp.json()
                outputs = data.get("output") or []
                dets: List[Detection] = []
                for o in outputs:
                    try:
                        x1 = float(o.get("x1", 0)); y1 = float(o.get("y1", 0))
                        x2 = float(o.get("x2", 0)); y2 = float(o.get("y2", 0))
                        score = float(o.get("score", 0)); cls = str(o.get("class", "object"))
                        dets.append(Detection(x1=x1, y1=y1, x2=x2, y2=y2, score=score, cls=cls))
                    except Exception:
                        continue
                return dets
            except Exception as e:
                last_exc = e
                import time as _t
                _t.sleep(delay)
        return []


