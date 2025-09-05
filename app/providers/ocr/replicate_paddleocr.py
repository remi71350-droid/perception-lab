from __future__ import annotations

from typing import List, Any, Dict
import os
import requests


class ReplicatePaddleOcr:
    def __init__(self, version: str) -> None:
        self.version = version
        self.token = os.getenv("REPLICATE_API_TOKEN", "")

    def infer(self, image_b64: str) -> List[dict]:
        if not self.token:
            return []
        headers = {"Authorization": f"Token {self.token}", "Content-Type": "application/json"}
        url = "https://api.replicate.com/v1/predictions"
        payload: Dict[str, Any] = {"version": self.version, "input": {"image": image_b64}}
        backoffs = [0.5, 1.0, 2.0]
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
                out = data.get("output") or []
                ocr_items: List[dict] = []
                for it in out:
                    try:
                        text = it.get("text")
                        box = it.get("box")
                        if text and box and len(box) == 4:
                            ocr_items.append({"text": str(text), "box": [float(x) for x in box]})
                    except Exception:
                        continue
                return ocr_items
            except Exception:
                import time as _t
                _t.sleep(delay)
        return []


