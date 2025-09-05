from __future__ import annotations

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import os
from fastapi.responses import JSONResponse, PlainTextResponse
import json
from datetime import datetime, timezone
import base64
from pathlib import Path
import numpy as np
import cv2

from .schemas import EvaluateRequest, ReportRequest, RunFrameRequest, RunVideoRequest
from .metrics import get_metrics_registry
from .storage import RunRegistry
from app.utils.config import load_providers_config
from app.providers.detection.replicate import ReplicateDetector
from app.utils.viz import draw_boxes, draw_track_ids, overlay_soft_masks, draw_ocr_labels
from app.utils.timing import StageTimer, timed
from app.providers.tracking.bytetrack import SimpleTracker
from app.providers.segmentation.hf import HfSegmentation
from app.providers.ocr.replicate_paddleocr import ReplicatePaddleOcr


app = FastAPI(title="Perception Ops Lab API", version="0.1.0")

# Enable CORS for local Streamlit UI
_cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

registry = RunRegistry()
metrics = get_metrics_registry()
_stop_requested: bool = False


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/health/providers")
def health_providers() -> dict:
    """Report readiness of cloud providers used by the API for online mode."""
    ready: dict[str, bool] = {}
    # Replicate
    ready["replicate_token"] = bool(os.getenv("REPLICATE_API_TOKEN"))
    # HF segmentation endpoint
    ready["hf_api_token"] = bool(os.getenv("HF_API_TOKEN"))
    ready["hf_seg_endpoint"] = bool(os.getenv("HF_SEG_ENDPOINT"))
    # OCR version (replicate)
    try:
        prov = load_providers_config().get("ocr", {})
    except Exception:
        prov = {}
    ready["replicate_paddleocr_version"] = bool(prov.get("version"))
    return {"status": "ok", "providers": ready}


@app.post("/run_frame")
def run_frame(req: RunFrameRequest) -> dict:
    # Process a single frame and persist artifacts
    run_id = registry.ensure_run()
    # Minimal provider wiring
    providers = load_providers_config()
    det_cfg = providers.get("detection", {})
    if req.provider_override and isinstance(req.provider_override, dict):
        det_cfg = req.provider_override.get("detection", det_cfg)
    det_provider = det_cfg.get("provider", "replicate")
    det_model = det_cfg.get("model", "ultralytics/yolov8")
    boxes = []
    timer = StageTimer()
    if det_provider == "replicate":
        with timed(timer, "model"):
            det = ReplicateDetector(det_model)
            boxes = [
                {
                    "x1": d.x1,
                    "y1": d.y1,
                    "x2": d.x2,
                    "y2": d.y2,
                    "score": d.score,
                    "cls": d.cls,
                }
                for d in det.infer(req.image_b64)
            ]

    # Decode input and produce annotated overlay if possible
    annotated_b64 = None
    annotated_path = None
    try:
        img_bytes = base64.b64decode(req.image_b64.encode("utf-8"))
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        img = None

    if img is not None:
        box_tuples = [(b["x1"], b["y1"], b["x2"], b["y2"]) for b in boxes]
        vis = draw_boxes(img, box_tuples) if box_tuples else img.copy()
        # Real segmentation overlay if configured
        try:
            seg = HfSegmentation(model_id="seg")
            masks = seg.infer(req.image_b64)
            # Expect either binary mask arrays or provider-specific; if binary buffers available, overlay
            bin_masks = []
            for m in masks:
                buf = m.get("mask") if isinstance(m, dict) else None
                if buf is not None:
                    import base64 as _b64, numpy as _np
                    raw = _b64.b64decode(buf)
                    arr2 = _np.frombuffer(raw, dtype=_np.uint8)
                    # Fallback shape; real endpoints should include shape metadata
                    try:
                        h, w = vis.shape[:2]
                        bin_masks.append(arr2.reshape(h, w))
                    except Exception:
                        continue
            if bin_masks:
                vis = overlay_soft_masks(vis, bin_masks)
        except Exception:
            pass
        # Simple tracking stub computed before drawing track IDs
        tracks = SimpleTracker().update(boxes)
        vis = draw_track_ids(vis, tracks)
        # OCR labels if configured (Replicate PaddleOCR)
        ocr_items = []
        try:
            ocr = providers.get("ocr", {})
            ocr_provider = ocr.get("provider", "gcv")
            if req.provider_override and isinstance(req.provider_override, dict):
                ocr = req.provider_override.get("ocr", ocr)
                ocr_provider = ocr.get("provider", ocr_provider)
            if str(ocr_provider).startswith("replicate"):
                version = ocr.get("version", "")
                if version:
                    ocr_items = ReplicatePaddleOcr(version=version).infer(req.image_b64)
            vis = draw_ocr_labels(vis, ocr_items)
        except Exception:
            pass
        ok, buf = cv2.imencode(".jpg", vis)
        if ok:
            jpg_bytes = buf.tobytes()
            annotated_b64 = base64.b64encode(jpg_bytes).decode("utf-8")
            run_dir = Path("runs") / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            existing = sorted(run_dir.glob("annotated_*.jpg"))
            if len(existing) < 3:
                next_idx = len(existing)
                out_path = run_dir / f"annotated_{next_idx:03d}.jpg"
                out_path.write_bytes(jpg_bytes)
                annotated_path = str(out_path)

    # Apply overlay filters (class include) if provided
    class_include = None
    if req.overlay_opts and isinstance(req.overlay_opts, dict):
        class_include = req.overlay_opts.get("class_include")
    if class_include:
        boxes = [b for b in boxes if b.get("cls") in class_include]

    # Simple tracking already computed above when img is not None; ensure defined
    if 'tracks' not in locals():
        tracks = SimpleTracker().update(boxes)

    # Export basic metrics
    if "model" in timer.timings_ms:
        metrics.latency_model_ms.observe(timer.timings_ms["model"]) 

    total_ms = sum(timer.timings_ms.values()) or 1e-6
    fps_val = 1000.0 / total_ms

    event = {
        "boxes": boxes,
        "masks": [],
        "tracks": tracks,
        "ocr": ocr_items if 'ocr_items' in locals() else [],
        "timings": {
            "model": round(timer.timings_ms.get("model", 0.0), 2),
        },
        "frame_id": 0,
        "run_id": run_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "fps": fps_val,
        "provider_provenance": {"detector": f"replicate:{det_model}", "ocr": "gcv"},
        "errors": [],
        "annotated_path": annotated_path,
        "annotated_b64": annotated_b64,
    }
    registry.append_event(run_id, json.dumps(event))
    return event


@app.post("/run_video")
def run_video(req: RunVideoRequest) -> JSONResponse:
    # WebSocket stream is planned; acknowledge request for now
    run_id = registry.ensure_run()
    return JSONResponse({"status": "accepted", "run_id": run_id, "note": "WS stream TBD"})


@app.post("/run_control")
def run_control(payload: dict) -> dict:
    """Simple control endpoint; currently supports action=="stop"."""
    global _stop_requested
    action = str(payload.get("action", "")).lower()
    if action == "stop":
        _stop_requested = True
        return {"ok": True, "action": action}
    return {"ok": False, "error": "unsupported action"}


@app.post("/evaluate")
def evaluate(req: EvaluateRequest) -> dict:
    # Call evaluator agent placeholder and persist
    from app.agents.evaluator import EvaluatorAgent
    run_id = registry.last_run_id() or registry.ensure_run()
    agent = EvaluatorAgent(config={})
    result = agent.evaluate(req.dataset, req.tasks)
    result.update({"run_id": run_id})
    run_dir = Path("runs") / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


@app.post("/report")
def report(req: ReportRequest) -> dict:
    # Build report using report service
    from .report import build_pdf_report
    run_dir = Path("runs") / req.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = build_pdf_report(run_dir)
    return {"report_path": str(path)}


@app.get("/metrics")
def prometheus_metrics() -> Response:
    content, content_type = metrics.export_prometheus_text()
    return PlainTextResponse(content=content, media_type=content_type)


@app.get("/last_event")
def last_event() -> JSONResponse:
    run_id = registry.last_run_id()
    if not run_id:
        return JSONResponse({"run_id": None, "event": None})
    evt = registry.read_last_event(run_id)
    try:
        parsed = json.loads(evt) if evt else None
    except Exception:
        parsed = evt
    return JSONResponse({"run_id": run_id, "event": parsed})


@app.websocket("/ws/run_video")
async def ws_run_video(ws: WebSocket) -> None:
    await ws.accept()
    cap = None
    try:
        params = dict(ws.query_params)
        video_path = params.get("video_path", "data/samples/day.mp4")
        profile = params.get("profile", "realtime")
        run_id = registry.ensure_run()
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            await ws.send_json({"error": f"cannot open video: {video_path}"})
            await ws.close()
            return
        frame_id = 0
        timer = StageTimer()
        providers = load_providers_config()
        det_cfg = providers.get("detection", {})
        det_model = det_cfg.get("model", "ultralytics/yolov8")
        global _stop_requested
        _stop_requested = False
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if _stop_requested:
                break
            h, w = frame.shape[:2]
            # Encode frame to base64 for provider calls
            ok2, buf = cv2.imencode(".jpg", frame)
            if not ok2:
                break
            b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
            # Detection
            with timed(timer, "model"):
                det = ReplicateDetector(det_model)
                dets = det.infer(b64)
            boxes = [{"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2, "score": d.score, "cls": d.cls} for d in dets]
            # Tracking
            tracks = SimpleTracker().update(boxes)
            # Build event
            total_ms = sum(timer.timings_ms.values()) or 1e-6
            fps_val = 1000.0 / total_ms
            event = {
                "run_id": run_id,
                "frame_id": frame_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "timings": {"model": round(timer.timings_ms.get("model", 0.0), 2)},
                "fps": fps_val,
                "boxes": boxes,
                "tracks": tracks,
                "masks": [],
                "ocr": [],
                "provider_provenance": {"detector": f"replicate:{det_model}", "ocr": ""},
                "errors": [],
                "shape": {"w": w, "h": h},
            }
            registry.append_event(run_id, json.dumps(event))
            metrics.fps.set(event["fps"])  # basic metric update
            await ws.send_json(event)
            frame_id += 1
        await ws.close()
    except WebSocketDisconnect:
        return
    finally:
        if cap is not None:
            cap.release()


@app.post("/ab_compare")
def ab_compare(payload: dict) -> dict:
    """Render a single representative frame in both profiles and save side-by-side assets.

    Writes runs/latest/realtime_frame.png and runs/latest/accuracy_frame.png.
    """
    video_path = payload.get("video_path", "data/samples/day.mp4")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"ok": False, "error": f"cannot open video: {video_path}"}
    # Seek to midpoint frame if possible
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if total > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
    except Exception:
        pass
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return {"ok": False, "error": "failed to read frame"}
    ok2, buf = cv2.imencode(".jpg", frame)
    if not ok2:
        return {"ok": False, "error": "encode failure"}
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
    providers = load_providers_config()
    det_cfg = providers.get("detection", {})
    det_model = det_cfg.get("model", "ultralytics/yolov8")
    # Helper to annotate
    def _annotate(img_b64: str) -> tuple[list[dict], np.ndarray]:
        det = ReplicateDetector(det_model)
        dets = det.infer(img_b64)
        boxes = [{"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2} for d in dets]
        arr = cv2.imdecode(np.frombuffer(base64.b64decode(img_b64), dtype=np.uint8), cv2.IMREAD_COLOR)
        vis = draw_boxes(arr, [(b["x1"], b["y1"], b["x2"], b["y2"]) for b in boxes]) if boxes else arr
        return boxes, vis
    # Realtime
    _, vis_rt = _annotate(b64)
    # Accuracy (same flow for now; in a real setup you would swap models/providers)
    _, vis_ac = _annotate(b64)
    out = Path("runs/latest")
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "realtime_frame.png"), vis_rt)
    cv2.imwrite(str(out / "accuracy_frame.png"), vis_ac)
    return {"ok": True}


@app.post("/clear")
def clear() -> dict:
    """Remove artifacts in runs/latest to reset UI state."""
    root = Path("runs/latest")
    if root.exists():
        for p in root.glob("*"):
            try:
                p.unlink()
            except Exception:
                pass
    return {"ok": True}


@app.get("/events_snapshot")
def events_snapshot(limit: int = 50) -> JSONResponse:
    run_id = registry.last_run_id()
    if not run_id:
        return JSONResponse({"run_id": None, "fps": [], "latency_pre": [], "latency_model": [], "latency_post": [], "frame_ids": []})
    path = Path("runs") / run_id / "events.jsonl"
    fps: list[float] = []
    lpre: list[float] = []
    lmod: list[float] = []
    lpost: list[float] = []
    fids: list[int] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines[-limit:]:
            try:
                obj = json.loads(line)
                fids.append(int(obj.get("frame_id", 0)))
                fps.append(float(obj.get("fps", 0.0)))
                t = obj.get("timings", {})
                lpre.append(float(t.get("pre", 0.0)))
                lmod.append(float(t.get("model", 0.0)))
                lpost.append(float(t.get("post", 0.0)))
            except Exception:
                continue
    return JSONResponse({"run_id": run_id, "fps": fps, "latency_pre": lpre, "latency_model": lmod, "latency_post": lpost, "frame_ids": fids})


@app.get("/load_metrics")
def load_metrics(run_id: str | None = None) -> JSONResponse:
    rid = run_id or registry.last_run_id()
    if not rid:
        return JSONResponse({"run_id": None, "metrics": None})
    path = Path("runs") / rid / "metrics.json"
    if not path.exists():
        return JSONResponse({"run_id": rid, "metrics": None})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = None
    return JSONResponse({"run_id": rid, "metrics": data})


@app.post("/export_run")
def export_run(payload: dict) -> dict:
    rid = payload.get("run_id") or registry.last_run_id()
    if not rid:
        return {"zip_path": None, "error": "no run id"}
    run_dir = Path("runs") / rid
    if not run_dir.exists():
        return {"zip_path": None, "error": "run dir not found"}
    import shutil
    zip_base = Path("runs") / f"{rid}_bundle"
    zip_file = shutil.make_archive(str(zip_base), "zip", str(run_dir))
    return {"zip_path": zip_file, "run_id": rid}


