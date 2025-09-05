from __future__ import annotations

"""
Generate starter offline assets for PerceptionLab.

Outputs per scenario under offline/<scenario>/:
  - realtime_frame.png (lighter overlays)
  - accuracy_frame.png (heavier overlays)
  - last_frame.png
  - events.jsonl (synthetic timings)

Usage:
  python tools/make_offline_assets.py            # all scenarios
  python tools/make_offline_assets.py day night  # specific scenarios
"""

import json
import random
import sys
from pathlib import Path
from typing import Iterable
from PIL import Image, ImageDraw, ImageFont


SCENARIOS = ["day", "night", "rain", "tunnel", "crosswalk", "snow"]


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _bg_for(scenario: str) -> tuple[int, int, int]:
    return {
        "day": (32, 120, 180),
        "night": (12, 18, 28),
        "rain": (26, 48, 72),
        "tunnel": (40, 32, 28),
        "crosswalk": (36, 60, 80),
        "snow": (54, 68, 82),
    }.get(scenario, (32, 48, 64))


def draw_placeholder(path: Path, scenario: str, label: str, boxes: int) -> None:
    W, H = 1280, 720
    im = Image.new("RGB", (W, H), _bg_for(scenario))
    d = ImageDraw.Draw(im, "RGBA")
    title = f"{scenario.capitalize()} — {label}"
    d.text((28, 24), title, fill=(210, 245, 255, 255))
    random.seed(hash((scenario, label)) & 0xFFFFFFFF)
    for _ in range(boxes):
        x1 = random.randint(60, W - 340)
        y1 = random.randint(60, H - 220)
        x2 = x1 + random.randint(140, 320)
        y2 = y1 + random.randint(80, 180)
        color = (2, 171, 193, 255) if label == "realtime" else (255, 128, 0, 255)
        d.rectangle([x1, y1, x2, y2], outline=color, width=3)
        d.rectangle([x1, y1 - 22, x1 + 120, y1], fill=(color[0], color[1], color[2], 160))
        d.text((x1 + 6, y1 - 20), "car", fill=(0, 0, 0, 255))
    im.save(path)


def make_events(path: Path, fps: int = 18, frames: int = 240, seed: int = 42) -> None:
    random.seed(seed)
    _ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        for i in range(frames):
            pre = round(random.uniform(2.0, 4.0), 2)
            model = round(random.uniform(38.0, 52.0), 2)
            post = round(random.uniform(3.0, 5.0), 2)
            row = {
                "frame_id": i,
                "fps": fps,
                "pre_ms": pre,
                "model_ms": model,
                "post_ms": post,
                "provider": "offline:yolov8",
                "level": ("warn" if random.random() < 0.03 else "info"),
            }
            f.write(json.dumps(row) + "\n")


def build_scenario(s: str) -> None:
    base = Path("offline") / s
    _ensure_dir(base)
    draw_placeholder(base / "realtime_frame.png", s, "realtime", boxes=2)
    draw_placeholder(base / "accuracy_frame.png", s, "accuracy", boxes=5)
    (base / "last_frame.png").write_bytes((base / "accuracy_frame.png").read_bytes())
    make_events(base / "events.jsonl", seed=hash(s) & 0xFFFFFFFF)


def main(args: Iterable[str]) -> None:
    targets = list(args) or SCENARIOS
    for s in targets:
        build_scenario(s)
        print(f"offline assets ready: offline/{s}")


if __name__ == "__main__":
    main(sys.argv[1:])


