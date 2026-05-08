"""Extract evenly-spaced keyframes from a video clip.

Used by the unified input channel so videos go through the same Claude vision
flow as photos. We don't transcribe audio — we just sample N frames so the AI
can see what was filmed (a walk-through of a room, a pan over a drawing,
existing condition vs proposed, etc).

Backend: OpenCV (opencv-python-headless). No ffmpeg dependency on the host.
"""
from __future__ import annotations

import io as _io
import os
import tempfile

from PIL import Image


def extract_video_keyframes(
    video_bytes: bytes,
    n_frames: int = 8,
    suffix: str = ".mp4",
) -> list[tuple[bytes, str, str]]:
    """Sample `n_frames` evenly-spaced frames from a video.

    Returns a list of `(png_bytes, mime, name)` tuples ready to be queued as
    unified inputs. Empty list if the video is unreadable.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return []

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(video_bytes)
        path = f.name

    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return []
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        if total <= 0:
            cap.release()
            return []

        n = max(1, min(n_frames, total))
        if n == 1:
            indices = [total // 2]
        else:
            indices = [int(round(i * (total - 1) / (n - 1))) for i in range(n)]

        frames: list[tuple[bytes, str, str]] = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            # Cap dimensions so each frame stays under the vision-payload budget.
            img.thumbnail((1600, 1600), Image.LANCZOS)
            buf = _io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            ts = (idx / fps) if fps else 0.0
            frames.append((buf.getvalue(), "image/png", f"frame-{idx:06d}-t{ts:0.1f}s.png"))
        cap.release()
        return frames
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


VIDEO_EXTS = {"mp4", "mov", "webm", "m4v", "avi", "mkv"}


def is_video_filename(name: str) -> bool:
    return name.lower().rsplit(".", 1)[-1] in VIDEO_EXTS
