from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from typing import List, Dict, Optional, Tuple


class BoundingBox(BaseModel):
    x1: int = Field(..., description="Top-left X coordinate in pixels")
    y1: int = Field(..., description="Top-left Y coordinate in pixels")
    x2: int = Field(..., description="Bottom-right X coordinate in pixels")
    y2: int = Field(..., description="Bottom-right Y coordinate in pixels")

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)


class DetectedObject(BaseModel):
    class_id: int = Field(..., description="COCO or custom class identifier")
    class_name: str = Field(..., description="Human-readable category name (e.g., person, box)")
    class_name: str = Field(..., description="Human-readable category name (e.g., Person, Box)")
    confidence: float = Field(..., description="Detection confidence between 0.0 and 1.0")
    bbox: BoundingBox = Field(..., description="Pixel bounding box coordinates")
    track_id: Optional[int] = Field(None, description="Persistent ByteTrack multi-object tracking ID")


class TrackPoint(BaseModel):
    timestamp_seconds: float
    x: int
    y: int


class TrackSummary(BaseModel):
    track_id: int = Field(..., description="Unique tracking identifier")
    class_name: str = Field(..., description="Detected category")
    first_seen_sec: float = Field(..., description="Timestamp when entity first entered footage")
    last_seen_sec: float = Field(..., description="Timestamp when entity was last tracked")
    total_detections: int = Field(..., description="Total frames in which entity was tracked")
    avg_speed_px_per_sec: float = Field(0.0, description="Average velocity across tracked frames")
    max_speed_px_per_sec: float = Field(0.0, description="Peak recorded velocity in px/sec")
    recent_path: List[Tuple[int, int]] = Field(default_factory=list, description="Recent centroid coordinates")


class FrameDetectionSummary(BaseModel):
    frame_index: int = Field(..., description="Sequential index of the video frame")
    timestamp_seconds: float = Field(..., description="Timestamp in seconds from video start")
    objects: List[DetectedObject] = Field(default_factory=list, description="List of objects detected in frame")
    objects: List[DetectedObject] = Field(default_factory=list, description="List of objects detected and tracked in frame")


class VideoAnalysisResponse(BaseModel):
    video_id: str = Field(..., description="Unique video session identifier")
    status: str = Field("completed", description="Status of the analysis")
    total_frames_analyzed: int = Field(0, description="Total sampled frames processed by YOLO")
    total_frames_analyzed: int = Field(0, description="Total sampled frames processed")
    total_detections: int = Field(0, description="Sum of all detections across frames")
    unique_tracks_count: int = Field(0, description="Total unique entities tracked across time")
    class_counts: Dict[str, int] = Field(default_factory=dict, description="Count of occurrences per class")
    avg_inference_time_ms: float = Field(0.0, description="Average YOLO model inference time per frame in milliseconds")
    avg_inference_time_ms: float = Field(0.0, description="Average model inference time per frame in milliseconds")
    processing_fps: float = Field(0.0, description="Overall pipeline throughput in frames per second")
    annotated_video_url: str = Field(..., description="API endpoint URL to stream the annotated output video")
    frames: List[FrameDetectionSummary] = Field(default_factory=list, description="Per-frame detection log")
    tracked_entities: List[TrackSummary] = Field(default_factory=list, description="Summary of all tracked entities and speeds")
    frames: List[FrameDetectionSummary] = Field(default_factory=list, description="Per-frame detection and tracking log")

