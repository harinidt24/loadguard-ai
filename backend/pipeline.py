"""
Full pipeline in one file: OpenCV sampling -> YOLO detection+tracking ->
trajectory building -> behaviour rules -> risk scoring -> evidence frames.
Consolidated into one file deliberately, for hackathon speed.
"""
import cv2, math
from collections import defaultdict
from ultralytics import YOLO

FRAME_SAMPLE_RATE = 3
INFERENCE_WIDTH = 640

PROXY_CLASS_MAP = {
    "person": "person", "suitcase": "carton", "backpack": "carton",
    "handbag": "carton", "truck": "vehicle", "car": "vehicle", "bus": "vehicle",
}

THRESHOLDS = {
    "drop_velocity_y": 120, "throw_velocity": 200, "direction_change_deg": 80,
    "drag_velocity_x": 60, "drag_max_velocity_y": 100, "drag_min_duration_seconds": 0.6,
    "proximity_distance_px": 120, "proximity_relative_speed": 200,
}

BEHAVIOUR_WEIGHTS = {"drop": 70, "throw": 85, "drag": 55, "proximity_risk": 90}
RISK_THRESHOLDS = [(85, "critical"), (65, "high"), (40, "medium"), (0, "low")]

EXPLANATIONS = {
    "drop": "{obj} showed a rapid downward motion followed by a sudden stop, consistent with a possible drop.",
    "throw": "{obj} moved at high speed with an abrupt direction change, consistent with a possible throw.",
    "drag": "{obj} moved horizontally for {dur}s with minimal vertical movement, consistent with dragging.",
    "proximity_risk": "A person and a vehicle came close together while moving quickly, indicating a possible proximity hazard.",
}
ACTIONS = {
    "drop": "Inspect the item for damage and review handling technique.",
    "throw": "Review footage with the operator; reinforce safe-handling protocol.",
    "drag": "Flag for equipment check and coach proper lifting technique.",
    "proximity_risk": "Review pedestrian/vehicle separation in this zone.",
}

_model = None


def get_model():
    global _model
    if _model is None:
        _model = YOLO("yolov8n.pt")
    return _model


def sample_frames(filepath):
    cap = cv2.VideoCapture(filepath)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % FRAME_SAMPLE_RATE == 0:
            h, w = frame.shape[:2]
            if w > INFERENCE_WIDTH:
                scale = INFERENCE_WIDTH / w
                frame = cv2.resize(frame, (INFERENCE_WIDTH, int(h * scale)))
            yield idx / fps, frame
        idx += 1
    cap.release()


def detect_and_track(frame):
    model = get_model()
    results = model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False)
    detections = []
    if not results or results[0].boxes is None:
        return detections
    names = results[0].names
    for box in results[0].boxes:
        class_name = names[int(box.cls[0])]
        if class_name not in PROXY_CLASS_MAP:
            continue
        track_id = int(box.id[0]) if box.id is not None else None
        if track_id is None:
            continue
        conf = float(box.conf[0])
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
        detections.append({"track_id": track_id, "class_name": PROXY_CLASS_MAP[class_name],
                            "confidence": conf, "bbox": (x1, y1, x2, y2)})
    return detections


def _velocity(p1, p2):
    dt = p2["t"] - p1["t"]
    if dt <= 0:
        return 0, 0
    return (p2["cx"] - p1["cx"]) / dt, (p2["cy"] - p1["cy"]) / dt


def _angle(vx, vy):
    return math.degrees(math.atan2(vy, vx))


def run_behaviour_rules(tracks):
    raw = []
    for track_id, pts in tracks.items():
        if len(pts) >= 3:
            for i in range(1, len(pts) - 1):
                pv = _velocity(pts[i - 1], pts[i])
                nv = _velocity(pts[i], pts[i + 1])
                sb, sa = math.hypot(*pv), math.hypot(*nv)
                ang = abs(_angle(*pv) - _angle(*nv))
                ang = min(ang, 360 - ang)
                if abs(pv[1]) > 80 and sa < sb * 0.6:
                    raw.append({"behaviour_type": "drop", "t": pts[i]["t"], "class_name": pts[i]["class_name"],
                                "confidence": min(0.95, pts[i]["conf"] + 0.1), "meta": {}, "point": pts[i]})
                elif sb > 150 or (sb > 100 and ang > 60):
                    raw.append({"behaviour_type": "throw", "t": pts[i]["t"], "class_name": pts[i]["class_name"],
                                "confidence": min(0.9, pts[i]["conf"]), "meta": {}, "point": pts[i]})
            window_start = 0
            for i in range(1, len(pts)):
                vx, vy = _velocity(pts[i - 1], pts[i])
                if abs(vx) > THRESHOLDS["drag_velocity_x"] and abs(vy) < THRESHOLDS["drag_max_velocity_y"]:
                    dur = pts[i]["t"] - pts[window_start]["t"]
                    if dur >= THRESHOLDS["drag_min_duration_seconds"]:
                        raw.append({"behaviour_type": "drag", "t": pts[i]["t"], "class_name": pts[i]["class_name"],
                                    "confidence": min(0.85, pts[i]["conf"]), "meta": {"dur": round(dur, 1)}, "point": pts[i]})
                        window_start = i
                else:
                    window_start = i
    return raw


def score_event(raw):
    weight = BEHAVIOUR_WEIGHTS.get(raw["behaviour_type"], 50)
    score = round(min(100, weight * raw["confidence"]), 1)
    level = next(lvl for thresh, lvl in RISK_THRESHOLDS if score >= thresh)
    explanation = EXPLANATIONS[raw["behaviour_type"]].format(
        obj=raw["class_name"], dur=raw["meta"].get("dur", "?"))
    return {
        "timestamp_seconds": raw["t"], "behaviour_type": raw["behaviour_type"],
        "object_type": raw["class_name"], "risk_score": score, "risk_level": level,
        "confidence": raw["confidence"], "explanation": explanation,
        "recommended_action": ACTIONS[raw["behaviour_type"]],
    }


def run_pipeline(video_path, evidence_dir):
    tracks = defaultdict(list)
    frames_by_time = {}

    for t, frame in sample_frames(video_path):
        dets = detect_and_track(frame)
        for d in dets:
            x1, y1, x2, y2 = d["bbox"]
            tracks[d["track_id"]].append({
                "t": t, "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2, "bbox": (x1, y1, x2, y2),
                "class_name": d["class_name"], "conf": d["confidence"],
            })
        frames_by_time[round(t, 1)] = frame.copy()
       
    raw_events = run_behaviour_rules(tracks)
    events = []
    for i, raw in enumerate(raw_events):
        scored = score_event(raw)
        frame = frames_by_time.get(round(scored["timestamp_seconds"], 1))
        evidence_path = None
        if frame is not None:
            frame = frame.copy()
            bbox = raw.get("point", {}).get("bbox")
            if bbox:
                x1, y1, x2, y2 = [int(v) for v in bbox]
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), 2)
                cv2.putText(frame, scored["behaviour_type"].upper(), (x1, max(y1 - 8, 15)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
            fname = f"event_{i}.jpg"
            cv2.imwrite(str(evidence_dir / fname), frame)
            evidence_path = f"/evidence/{fname}"
        scored["evidence_path"] = evidence_path
        events.append(scored)

    return events