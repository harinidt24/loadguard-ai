from collections import deque
import math
from typing import Dict, List, Tuple, Optional
import cv2
import numpy as np

from schemas.detection import BoundingBox, TrackSummary


class WarehouseTracker:
    """
    WarehouseTracker maintains temporal trajectory history, computes kinematic metrics
    (velocities, vertical drop rates), and renders motion breadcrumbs for tracked entities.
    """

    def __init__(self, max_history_len: int = 40):
        self.max_history_len = max_history_len
        # track_id -> dict with history, timestamps, class_name, etc.
        self.track_data: Dict[int, Dict] = {}

    def reset(self):
        """Clears all tracking histories for a new video session."""
        self.track_data.clear()

    def update_track(
        self,
        track_id: int,
        class_name: str,
        bbox: BoundingBox,
        timestamp_sec: float
    ) -> float:
        """
        Updates trajectory history for track_id and computes instantaneous velocity (px/sec).
        Returns the instantaneous speed.
        """
        cx, cy = bbox.center

        if track_id not in self.track_data:
            self.track_data[track_id] = {
                "class_name": class_name,
                "first_seen": timestamp_sec,
                "last_seen": timestamp_sec,
                "count": 1,
                "history": deque(maxlen=self.max_history_len),
                "speeds": [],
                "current_speed": 0.0,
                "vx": 0.0,
                "vy": 0.0,
            }
            self.track_data[track_id]["history"].append((timestamp_sec, cx, cy, bbox))
            return 0.0

        record = self.track_data[track_id]
        record["last_seen"] = timestamp_sec
        record["count"] += 1
        record["class_name"] = class_name

        # Calculate velocity based on last recorded centroid
        prev_time, prev_x, prev_y, _ = record["history"][-1]
        dt = timestamp_sec - prev_time

        if dt > 0.001:
            dx = cx - prev_x
            dy = cy - prev_y  # Note: in computer vision, positive dy means downward motion!
            vx = dx / dt
            vy = dy / dt
            speed = math.sqrt(dx**2 + dy**2) / dt

            record["vx"] = round(vx, 1)
            record["vy"] = round(vy, 1)
            record["current_speed"] = round(speed, 1)
            record["speeds"].append(speed)
        else:
            speed = record["current_speed"]

        record["history"].append((timestamp_sec, cx, cy, bbox))
        return speed

    def get_kinematics(self, track_id: int) -> Tuple[float, float, float]:
        """
        Returns (vx, vy, speed) in pixels/sec for the given track_id.
        vy > 0 indicates downward motion.
        """
        if track_id not in self.track_data:
            return 0.0, 0.0, 0.0
        r = self.track_data[track_id]
        return r.get("vx", 0.0), r.get("vy", 0.0), r.get("current_speed", 0.0)

    def draw_motion_trail(
        self,
        frame: np.ndarray,
        track_id: int,
        color: Tuple[int, int, int]
    ) -> np.ndarray:
        """
        Draws a dynamic breadcrumb trajectory path showing recent movement history.
        Older points are thinner and more transparent.
        """
        if track_id not in self.track_data:
            return frame

        history = self.track_data[track_id]["history"]
        if len(history) < 2:
            return frame

        pts = [(pt[1], pt[2]) for pt in history]
        num_pts = len(pts)

        for i in range(1, num_pts):
            # Dynamic thickness increasing towards current position
            thickness = int(math.sqrt(64 * float(i) / num_pts)) + 1
            cv2.line(frame, pts[i - 1], pts[i], color, thickness)

        # Draw a bright center dot at the current location
        cv2.circle(frame, pts[-1], 4, (255, 255, 255), -1)
        return frame

    def get_summaries(self) -> List[TrackSummary]:
        """Compiles TrackSummary records for all tracked entities."""
        summaries: List[TrackSummary] = []
        for t_id, data in self.track_data.items():
            speeds = data.get("speeds", [])
            avg_spd = round(sum(speeds) / len(speeds), 1) if speeds else 0.0
            max_spd = round(max(speeds), 1) if speeds else 0.0
            recent = [(pt[1], pt[2]) for pt in data["history"]]

            summaries.append(
                TrackSummary(
                    track_id=t_id,
                    class_name=data["class_name"],
                    first_seen_sec=round(data["first_seen"], 2),
                    last_seen_sec=round(data["last_seen"], 2),
                    total_detections=data["count"],
                    avg_speed_px_per_sec=avg_spd,
                    max_speed_px_per_sec=max_spd,
                    recent_path=recent[-15:],  # Last 15 waypoints
                )
            )

        # Sort by first appearance
        summaries.sort(key=lambda s: s.first_seen_sec)
        return summaries

