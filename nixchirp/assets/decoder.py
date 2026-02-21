"""Unified animation decoder for GIF, APNG, WebM, MP4 using PyAV."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FrameInfo:
    """Metadata about a decoded frame."""

    index: int
    timestamp_ms: float
    duration_ms: float


@dataclass
class AnimationInfo:
    """Metadata about an animation file."""

    path: Path
    width: int
    height: int
    frame_count: int
    duration_ms: float
    fps: float
    has_alpha: bool


class AnimationDecoder:
    """Decodes animation files frame-by-frame into RGBA numpy arrays.

    Supports GIF, APNG, WebM (VP8/VP9 with alpha), and MP4.
    Uses PyAV (FFmpeg) for uniform decoding across formats.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Animation file not found: {self.path}")

        self._container: av.container.InputContainer | None = None
        self._stream: av.video.stream.VideoStream | None = None
        self._info: AnimationInfo | None = None
        self._frame_timestamps: list[FrameInfo] = []

    def open(self) -> AnimationInfo:
        """Open the file and probe its metadata."""
        self._container = av.open(str(self.path))
        self._stream = self._container.streams.video[0]

        # Probe frame count and timing
        stream = self._stream
        width = stream.codec_context.width
        height = stream.codec_context.height

        # Determine FPS
        if stream.average_rate:
            fps = float(stream.average_rate)
        elif stream.guessed_rate:
            fps = float(stream.guessed_rate)
        else:
            fps = 30.0  # fallback

        # Check for alpha support
        pix_fmt = stream.codec_context.pix_fmt or ""
        has_alpha = "a" in pix_fmt or "rgba" in pix_fmt or "yuva" in pix_fmt

        # For GIF/APNG, count frames by iterating (they're small)
        # For video formats, use stream.frames or duration
        frame_count = stream.frames
        if not frame_count or frame_count == 0:
            # Need to count by decoding
            frame_count = self._count_frames()

        duration_ms = 0.0
        if stream.duration and stream.time_base:
            duration_ms = float(stream.duration * stream.time_base) * 1000.0
        elif frame_count > 0 and fps > 0:
            duration_ms = (frame_count / fps) * 1000.0

        self._info = AnimationInfo(
            path=self.path,
            width=width,
            height=height,
            frame_count=frame_count,
            duration_ms=duration_ms,
            fps=fps,
            has_alpha=has_alpha,
        )

        # Reset to beginning for decoding
        self._seek_to_start()

        return self._info

    def _count_frames(self) -> int:
        """Count frames by iterating through the container."""
        count = 0
        for _ in self._container.decode(video=0):
            count += 1
        self._seek_to_start()
        return count

    def _seek_to_start(self) -> None:
        """Seek back to the beginning of the stream."""
        if self._container:
            self._container.seek(0, stream=self._stream)

    @property
    def info(self) -> AnimationInfo | None:
        return self._info

    def decode_all_frames(self) -> list[np.ndarray]:
        """Decode all frames into a list of RGBA numpy arrays.

        Returns:
            List of numpy arrays, each with shape (height, width, 4) dtype uint8.
        """
        if not self._container:
            raise RuntimeError("Decoder not opened. Call open() first.")

        self._seek_to_start()
        frames: list[np.ndarray] = []

        for frame in self._container.decode(video=0):
            rgba = frame.to_ndarray(format="rgba")
            frames.append(rgba)

        self._seek_to_start()
        return frames

    def decode_frame(self, index: int) -> np.ndarray | None:
        """Decode a specific frame by index.

        For random access, this seeks and decodes — relatively expensive.
        Prefer decode_all_frames() or sequential iteration for bulk access.
        """
        if not self._container:
            raise RuntimeError("Decoder not opened. Call open() first.")

        self._seek_to_start()
        for i, frame in enumerate(self._container.decode(video=0)):
            if i == index:
                return frame.to_ndarray(format="rgba")
        return None

    def iter_frames(self):
        """Iterate over frames, yielding (index, rgba_array) tuples.

        Yields:
            Tuples of (frame_index, numpy_array) where array is RGBA uint8.
        """
        if not self._container:
            raise RuntimeError("Decoder not opened. Call open() first.")

        self._seek_to_start()
        for i, frame in enumerate(self._container.decode(video=0)):
            yield i, frame.to_ndarray(format="rgba")

    def close(self) -> None:
        """Release decoder resources."""
        if self._container:
            self._container.close()
            self._container = None
        self._stream = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
