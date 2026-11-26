"""Experimental 2D lead-arm extension counter, not a validated boxing coach.

The detector requires an approved MediaPipe Pose Landmarker .task model supplied
locally by the operator. No video frames or landmarks leave the machine.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, hypot, isfinite
from pathlib import Path

ARM = {'left': (11, 13, 15), 'right': (12, 14, 16)}


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    visibility: float = 1.0


def extension_ratio(points: dict[int, Point], arm: str) -> float | None:
    """Shoulder-wrist reach / combined arm segment lengths, not jab detection."""
    shoulder, elbow, wrist = (points.get(i) for i in ARM[arm])
    if any(p is None or p.visibility < 0.65 or not isfinite(p.x) or not isfinite(p.y)
           for p in (shoulder, elbow, wrist)):
        return None
    upper = hypot(elbow.x - shoulder.x, elbow.y - shoulder.y)
    lower = hypot(wrist.x - elbow.x, wrist.y - elbow.y)
    if upper < 0.015 or lower < 0.015:
        return None
    return min(1.0, hypot(wrist.x - shoulder.x, wrist.y - shoulder.y) / (upper + lower))


def count_extension_cycles(samples: list[tuple[float, float | None]],
                           extended: float = 0.93, reset: float = 0.82,
                           min_interval: float = 0.35) -> list[float]:
    """Count reset→extended→reset cycles with hysteresis and time separation."""
    state = 'needs_reset'
    last_event = float('-inf')
    events = []
    for timestamp, ratio in samples:
        if ratio is None or not isfinite(ratio):
            state = 'needs_reset'
            continue
        if state == 'needs_reset':
            if ratio <= reset:
                state = 'ready'
        elif state == 'ready':
            if ratio >= extended and timestamp - last_event >= min_interval:
                state = 'extended'
        elif state == 'extended' and ratio <= reset:
            events.append(round(timestamp, 2))
            last_event = timestamp
            state = 'ready'
    return events


def summarize_pose_samples(samples: list[tuple[float, float | None]], lead_arm: str,
                           total_frames: int) -> dict:
    visible = sum(value is not None for _, value in samples)
    coverage = visible / len(samples) if samples else 0.0
    sufficient = coverage >= 0.65 and visible >= 10
    events = count_extension_cycles(samples) if sufficient else []
    return {
        'analysis_type': 'experimental_pose_extension_v1',
        'technique_analyzed': False,
        'lead_arm': lead_arm,
        'sampled_frames': len(samples),
        'decoded_frames': total_frames,
        'usable_frame_fraction': round(coverage, 3),
        'extension_cycle_candidates': len(events) if sufficient else None,
        'candidate_timestamps_seconds': events,
        'quality': 'experimental' if sufficient else 'insufficient_pose_visibility',
        'message': (
            'Pose tracking estimated candidate lead-arm extension and return cycles.'
            if sufficient else
            'Not enough visible body landmarks for a defensible movement count. Try a steady, full-body, well-lit recording.'
        ),
        'limitations': [
            '2D landmarks cannot establish punch type, contact, force, or correct boxing technique.',
            'Camera angle, stance, occlusion and movement can create false counts.',
            'Results are not coaching or safety advice; expert validation is required.',
        ],
    }


def analyze_video(path: Path, model_path: Path, lead_arm: str = 'left') -> dict:
    """Decode ≤30s; sample ≤10 frames/sec; use MediaPipe Tasks VIDEO mode."""
    if lead_arm not in ARM:
        raise ValueError('lead_arm must be left or right')
    if not model_path.is_file():
        raise RuntimeError('Pose model asset missing; set TOPTIGER_POSE_MODEL to a local .task path')
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except ImportError as exc:
        raise RuntimeError('Install optional pose dependencies from requirements-pose.txt') from exc

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError('Could not decode uploaded video')
    fps = capture.get(cv2.CAP_PROP_FPS)
    frames_total = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    if not isfinite(fps) or fps <= 0 or fps > 240:
        capture.release()
        raise RuntimeError('Invalid video frame rate')
    if not isfinite(frames_total) or frames_total <= 0 or frames_total / fps > 30:
        capture.release()
        raise RuntimeError('Video must be no longer than 30 seconds')

    options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.6,
        min_pose_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    )
    samples = []
    count = 0
    stride = max(1, ceil(fps / 10))
    try:
        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            while count < frames_total:
                ok, frame = capture.read()
                if not ok:
                    break
                if count % stride == 0:
                    timestamp = count / fps
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    result = landmarker.detect_for_video(image, int(round(timestamp * 1000)))
                    points = {}
                    if len(result.pose_landmarks) == 1:
                        points = {i: Point(p.x, p.y, p.visibility or 0.0)
                                  for i, p in enumerate(result.pose_landmarks[0])}
                    samples.append((timestamp, extension_ratio(points, lead_arm)))
                count += 1
    finally:
        capture.release()
    if count == 0:
        raise RuntimeError('No decodable frames')
    result = summarize_pose_samples(samples, lead_arm, count)
    result['duration_seconds'] = round(count / fps, 2)
    return result
