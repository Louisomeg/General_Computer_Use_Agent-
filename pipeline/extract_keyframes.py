# =============================================================================
# Keyframe Extraction — detect GUI state changes via OpenCV MOG2
# =============================================================================
# Adapted from TongUI-Crawler's keyframe_extraction.py.
# Uses background subtraction to find frames where the UI changes significantly.
#
# FreeCAD-specific: masks the 3D viewport to ignore constant rotation/shading
# changes, focusing detection on menus, toolbars, and panels.
#
# Usage:
#   from pipeline.extract_keyframes import extract_keyframes
#   frames = extract_keyframes(Path("video.mp4"), Path("output/keyframes"))

import json
from pathlib import Path

import cv2
import numpy as np


def extract_keyframes(
    video_path: Path,
    output_dir: Path,
    threshold: int = 15000,
    min_gap_frames: int = 30,
    max_duration_s: int = 1200,
    mask_viewport: bool = True,
) -> list[dict]:
    """Extract keyframe PNGs using MOG2 background subtraction.

    Algorithm:
    1. Initialize MOG2 background subtractor
    2. For each frame, apply MOG2 and count non-zero pixels in foreground mask
    3. When count exceeds threshold -> GUI state change detected
    4. Group changes within min_gap_frames of each other (take representative)
    5. Save keyframes as PNGs

    Args:
        video_path: Path to MP4 video.
        output_dir: Directory to save keyframe PNGs.
        threshold: Minimum non-zero pixel count to trigger a keyframe.
                   FreeCAD-tuned default: 15000 (TongUI uses 10000).
        min_gap_frames: Minimum frames between keyframes (~1s at 30fps).
        max_duration_s: Skip videos longer than this (seconds).
        mask_viewport: If True, mask the 3D viewport area to reduce noise.

    Returns:
        List of {frame_number, timestamp, path} dicts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check for cached results
    manifest_path = output_dir / "keyframes.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            cached = json.load(f)
        # Verify PNGs still exist
        if all(Path(kf["path"]).exists() for kf in cached):
            print(f"[keyframes] Using cached: {len(cached)} keyframes")
            return cached

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = total_frames / fps

    if duration_s > max_duration_s:
        print(f"[keyframes] Video too long ({duration_s:.0f}s > {max_duration_s}s), skipping")
        cap.release()
        return []

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"[keyframes] Processing {video_path.name}: "
          f"{width}x{height}, {fps:.0f}fps, {duration_s:.0f}s")

    # Build viewport mask if requested
    viewport_mask = None
    if mask_viewport:
        viewport_mask = _build_viewport_mask(width, height)

    # MOG2 background subtractor
    bg_sub = cv2.createBackgroundSubtractorMOG2(
        history=500, varThreshold=16, detectShadows=False
    )

    # Sample rate: skip frames for high-fps videos (60fps -> analyze every 6th)
    sample_every = max(1, int(fps / 10))  # Target ~10 analysis frames per second

    # First pass: find candidate frames
    candidates = []
    frame_idx = 0
    last_keyframe_idx = -min_gap_frames  # Allow first frame
    progress_interval = int(total_frames / 10)  # Log every ~10%

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Progress logging
        if frame_idx > 0 and progress_interval > 0 and frame_idx % progress_interval == 0:
            pct = frame_idx / total_frames * 100
            print(f"[keyframes]   {pct:.0f}% ({frame_idx}/{total_frames} frames, "
                  f"{len(candidates)} candidates so far)")

        # Skip frames for performance (still feed to MOG2 to maintain model)
        if frame_idx % sample_every != 0:
            bg_sub.apply(frame, learningRate=0.01)
            frame_idx += 1
            continue

        # Apply MOG2
        fg_mask = bg_sub.apply(frame)

        # Apply viewport mask (zero out 3D viewport area)
        if viewport_mask is not None:
            fg_mask = cv2.bitwise_and(fg_mask, viewport_mask)

        # Threshold to binary
        _, binary = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)
        change_count = cv2.countNonZero(binary)

        if change_count > threshold and (frame_idx - last_keyframe_idx) >= min_gap_frames:
            candidates.append({
                "frame_number": frame_idx,
                "timestamp": frame_idx / fps,
                "change_count": change_count,
            })
            last_keyframe_idx = frame_idx

        frame_idx += 1

    cap.release()
    print(f"[keyframes] Found {len(candidates)} candidate keyframes")

    if not candidates:
        return []

    # Second pass: extract the actual keyframe images
    keyframes = _extract_frames(video_path, candidates, output_dir)

    # Save manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(keyframes, f, indent=2, default=str)

    print(f"[keyframes] Saved {len(keyframes)} keyframes to {output_dir}")
    return keyframes


def _build_viewport_mask(width: int, height: int) -> np.ndarray:
    """Build a mask that zeros out the FreeCAD 3D viewport region.

    FreeCAD typical layout:
    - Menu bar: top ~40px
    - Toolbar: next ~40px
    - Model tree: left ~250px
    - Tasks panel: left ~250px (below tree)
    - 3D viewport: center-right area
    - Python console: bottom ~60px

    The mask is WHITE (255) in areas we WANT to detect changes,
    and BLACK (0) in the 3D viewport area we want to ignore.
    """
    mask = np.ones((height, width), dtype=np.uint8) * 255

    # Zero out the approximate 3D viewport region
    # Left boundary: ~20% of width (right edge of model tree/tasks panel)
    # Top boundary: ~10% of height (below menu bar + toolbars)
    # Right boundary: 100% width
    # Bottom boundary: ~92% of height (above python console)
    vp_left = int(width * 0.20)
    vp_top = int(height * 0.10)
    vp_right = width
    vp_bottom = int(height * 0.92)

    mask[vp_top:vp_bottom, vp_left:vp_right] = 0

    return mask


def _extract_frames(
    video_path: Path,
    candidates: list[dict],
    output_dir: Path,
) -> list[dict]:
    """Re-read video and extract specific frames as PNGs."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot reopen video: {video_path}")

    # Build set of frame numbers to extract
    target_frames = {c["frame_number"]: i for i, c in enumerate(candidates)}
    keyframes = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx in target_frames:
            idx = target_frames[frame_idx]
            png_name = f"frame_{idx:04d}.png"
            png_path = output_dir / png_name
            cv2.imwrite(str(png_path), frame)

            keyframes.append({
                "frame_number": frame_idx,
                "timestamp": candidates[idx]["timestamp"],
                "path": str(png_path),
            })

        # Early exit if we've extracted all targets
        if len(keyframes) == len(candidates):
            break

        frame_idx += 1

    cap.release()
    return keyframes
