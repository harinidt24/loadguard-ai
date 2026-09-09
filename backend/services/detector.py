import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import cv2
import numpy as np
from ultralytics import YOLO

from schemas.detection import (
    BoundingBox,
    DetectedObject,
    FrameDetectionSummary,
    VideoAnalysisResponse,
)
from services.video_processor import VideoProcessor
from services.tracker import WarehouseTracker


class WarehouseDetector:
    """
    WarehouseDetector manages YOLOv8 model loading, entity inference,
    bounding-box visualization, and end-to-end video analysis.
    WarehouseDetector manages YOLOv8 object detection, ByteTrack multi-object tracking,
    motion trail rendering, and end-to-end video analysis.
    """

    _instance = None
    _model = None

    # Pretrained COCO class mappings relevant to warehouse environments
    CLASS_MAPPINGS: Dict[int, str] = {
        0: "Person",
        24: "Package / Bag",
        26: "Package / Bag",
        28: "Box / Parcel",
        39: "Item",
    }

    # Color palette (BGR format for OpenCV)
    COLORS = {
        "Person": (60, 220, 80),        # Bright Green
        "Box / Parcel": (0, 165, 255),   # Industrial Amber/Orange
        "Package / Bag": (255, 180, 0),  # Cyan-Yellow
        "Default": (240, 240, 60),       # Light Blue
    }

    def __init__(self, model_name: str = "yolov8n.pt", weights_dir: Optional[Path] = None):
        """
        Loads the YOLO model once into memory.
        Loads the YOLO model once into memory and initializes the tracker.
        """
        if WarehouseDetector._model is None:
            weights_path = model_name
            if weights_dir:
                weights_dir.mkdir(parents=True, exist_ok=True)
                weights_path = str(weights_dir / model_name)

            print(f"[WarehouseDetector] Loading YOLO model from '{weights_path}'...")
            WarehouseDetector._model = YOLO(weights_path)
            print("[WarehouseDetector] YOLO model loaded into memory successfully.")

        self.model = WarehouseDetector._model
        self.tracker = WarehouseTracker()

    def detect_frame(
    def track_frame(
        self,
        frame: np.ndarray,
        timestamp_sec: float = 0.0,
        conf_threshold: float = 0.35,
        target_classes: Optional[List[int]] = None,
    ) -> Tuple[List[DetectedObject], float]:
        """
        Performs object detection on a single frame.
        Returns (list_of_detections, inference_time_ms).
        Runs YOLOv8 detection + ByteTrack multi-object tracking on a single frame.
        Maintains persistent track IDs across frames and records trajectories.
        Returns (list_of_detected_and_tracked_objects, inference_time_ms).
        """
        start_time = time.perf_counter()

        # Run inference without extra console output
        classes_filter = target_classes if target_classes else list(self.CLASS_MAPPINGS.keys())
        results = self.model(

        # Execute tracking with ByteTrack persistence
        results = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            conf=conf_threshold,
            classes=classes_filter,
            verbose=False,
        )

        inference_time_ms = (time.perf_counter() - start_time) * 1000.0
        detections: List[DetectedObject] = []

        if not results or len(results) == 0:
            return detections, inference_time_ms

        boxes = results[0].boxes
        if boxes is None:
            return detections, inference_time_ms

        for box in boxes:
            cls_id = int(box.cls[0].item())
            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].tolist()

            # Extract persistent Track ID from ByteTrack
            track_id = int(box.id[0].item()) if box.id is not None else None
            class_name = self.CLASS_MAPPINGS.get(cls_id, f"Class_{cls_id}")

            bbox = BoundingBox(
                x1=int(xyxy[0]),
                y1=int(xyxy[1]),
                x2=int(xyxy[2]),
                y2=int(xyxy[3]),
            )

            # Update temporal trajectory history
            if track_id is not None:
                self.tracker.update_track(
                    track_id=track_id,
                    class_name=class_name,
                    bbox=bbox,
                    timestamp_sec=timestamp_sec,
                )

            detections.append(
                DetectedObject(
                    class_id=cls_id,
                    class_name=class_name,
                    confidence=round(conf, 3),
                    bbox=bbox,
                    track_id=track_id,
                )
            )

        return detections, inference_time_ms

    def annotate_frame(
        self,
        frame: np.ndarray,
        detections: List[DetectedObject],
        frame_number: Optional[int] = None,
        timestamp_sec: Optional[float] = None,
    ) -> np.ndarray:
        """
        Renders bounding boxes, category labels, and confidence tags on the frame.
        Renders bounding boxes, persistent Track IDs (#1, #2), motion breadcrumb
        trails, confidence scores, and an industrial status HUD.
        """
        annotated = frame.copy()

        # Step 1: Draw motion trails behind tracked entities first (so boxes appear on top)
        for obj in detections:
            if obj.track_id is not None:
                color = self.COLORS.get(obj.class_name, self.COLORS["Default"])
                annotated = self.tracker.draw_motion_trail(annotated, obj.track_id, color)

        # Step 2: Draw bounding boxes and identifier badges
        for obj in detections:
            bbox = obj.bbox
            color = self.COLORS.get(obj.class_name, self.COLORS["Default"])

            # 1. Draw bounding box rectangle
            # 1. Bounding box rectangle
            cv2.rectangle(
                annotated,
                (bbox.x1, bbox.y1),
                (bbox.x2, bbox.y2),
                color,
                thickness=2,
            )

            # 2. Draw label badge
            label = f"{obj.class_name} {int(obj.confidence * 100)}%"
            (w, h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            # 2. Label with persistent Track ID
            if obj.track_id is not None:
                label = f"#{obj.track_id} {obj.class_name} {int(obj.confidence * 100)}%"
            else:
                label = f"{obj.class_name} {int(obj.confidence * 100)}%"

            (w, h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)

            # Badge background
            label_y = max(bbox.y1 - 6, h + 6)
            cv2.rectangle(
                annotated,
                (bbox.x1, label_y - h - 4),
                (bbox.x1 + w + 8, label_y + 4),
                color,
                thickness=-1,
            )

            # Badge text (dark text on bright badge for high readability)
            # Badge text (dark on bright badge)
            cv2.putText(
                annotated,
                label,
                (bbox.x1 + 4, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                0.48,
                (10, 10, 10),
                thickness=1,
                lineType=cv2.LINE_AA,
            )

        # 3. Add top-left HUD overlay (timestamp and active worker count)
        # Step 3: Top-left Industrial HUD Overlay
        hud_text = []
        if timestamp_sec is not None:
            hud_text.append(f"T: {timestamp_sec:.2f}s")
        if frame_number is not None:
            hud_text.append(f"F#{frame_number}")

        worker_count = sum(1 for d in detections if d.class_name == "Person")
        active_track_count = sum(1 for d in detections if d.track_id is not None)
        hud_text.append(f"Workers: {worker_count}")
        hud_text.append(f"Tracked: {active_track_count}")

        hud_string = " | ".join(hud_text)
        cv2.putText(
            annotated,
            hud_string,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            0.62,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        return annotated

    def analyze_video(
        self,
        video_path: Path,
        output_path: Path,
        video_id: str,
        stride: int = 2,
        conf_threshold: float = 0.35,
    ) -> VideoAnalysisResponse:
        """
        Runs full YOLO object detection pipeline across video frames,
        writes annotated video to disk, and returns structured summary metrics.
        Runs full YOLO + ByteTrack tracking pipeline across video frames,
        writes annotated video with motion trails, and compiles tracking analytics.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        meta = VideoProcessor.validate_and_extract_metadata(
            video_path=video_path,
            video_id=video_id,
            original_filename=video_path.name,
        )

        if not meta.is_valid:
            raise ValueError(f"Cannot analyze invalid video: {meta.error_message}")

        # Configure VideoWriter
        # FourCC 'mp4v' or 'avc1' are standard for MP4 containers
        # Reset tracking histories for fresh video session
        self.tracker.reset()

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        effective_fps = max(round(meta.fps / stride, 2), 1.0)

        out_writer = cv2.VideoWriter(
            str(output_path),
            fourcc,
            effective_fps,
            (meta.width, meta.height),
        )

        frame_summaries: List[FrameDetectionSummary] = []
        total_inference_time = 0.0
        class_counts: Dict[str, int] = {}
        total_detections = 0
        frames_processed = 0

        pipeline_start = time.perf_counter()

        for frame_idx, timestamp, frame in VideoProcessor.sample_frames(video_path, stride=stride):
            detections, inf_time = self.detect_frame(
            detections, inf_time = self.track_frame(
                frame=frame,
                timestamp_sec=timestamp,
                conf_threshold=conf_threshold,
            )

            total_inference_time += inf_time
            frames_processed += 1
            total_detections += len(detections)

            for d in detections:
                class_counts[d.class_name] = class_counts.get(d.class_name, 0) + 1

            # Annotate frame
            annotated = self.annotate_frame(
                frame=frame,
                detections=detections,
                frame_number=frame_idx,
                timestamp_sec=timestamp,
            )

            out_writer.write(annotated)

            frame_summaries.append(
                FrameDetectionSummary(
                    frame_index=frame_idx,
                    timestamp_seconds=timestamp,
                    objects=detections,
                )
            )

        out_writer.release()
        total_pipeline_time = time.perf_counter() - pipeline_start

        avg_inference_ms = (
            round(total_inference_time / frames_processed, 2)
            if frames_processed > 0
            else 0.0
        )
        processing_fps = (
            round(frames_processed / total_pipeline_time, 2)
            if total_pipeline_time > 0
            else 0.0
        )

        # Retrieve comprehensive tracking analytics
        tracked_summaries = self.tracker.get_summaries()

        return VideoAnalysisResponse(
            video_id=video_id,
            status="completed",
            total_frames_analyzed=frames_processed,
            total_detections=total_detections,
            unique_tracks_count=len(tracked_summaries),
            class_counts=class_counts,
            avg_inference_time_ms=avg_inference_ms,
            processing_fps=processing_fps,
            annotated_video_url=f"/processed-video/{video_id}",
            tracked_entities=tracked_summaries,
            frames=frame_summaries,
        )

