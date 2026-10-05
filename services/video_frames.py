"""Video → ordered PNG frames."""

from __future__ import annotations

import os

import cv2


def extract_frames(video_path: str, out_dir: str, interval_sec: float, prefix: str = "frame") -> dict:
    os.makedirs(out_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if fps <= 0:
        fps = 24.0

    stride = max(1, int(round(fps * max(0.05, interval_sec))))

    idx = 0
    saved = 0
    meta_fps = fps

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % stride == 0:
            saved += 1
            fname = f"{prefix}_{saved:03d}.png"
            path = os.path.join(out_dir, fname)
            cv2.imwrite(path, frame)
        idx += 1

    cap.release()

    duration_sec = idx / fps if fps else None

    return {
        "frame_count": saved,
        "source_frames_read": idx,
        "effective_fps_estimate": fps,
        "stride": stride,
        "interval_requested_sec": interval_sec,
        "duration_approx_sec": duration_sec,
        "pattern": prefix + "_%03d.png",
    }


def reorganize_existing_frames(folder: str, prefix: str = "frame") -> list[str]:
    """Sort PNG names and rename to contiguous frame_001..."""
    import re
    def natural_sort_key(s: str) -> list:
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

    pngs = [n for n in os.listdir(folder) if n.lower().endswith(".png")]
    pngs.sort(key=natural_sort_key)
    renamed = []
    for i, old in enumerate(pngs, start=1):
        new_name = f"{prefix}_{i:03d}.png"
        src = os.path.join(folder, old)
        dst = os.path.join(folder, new_name)
        if os.path.abspath(src) == os.path.abspath(dst):
            renamed.append(new_name)
            continue
        if os.path.exists(dst):
            raise RuntimeError(f"Target exists: {dst}")
        os.replace(src, dst)
        renamed.append(new_name)
    return renamed
