"""Animation file loading — decodes and manages frame data for a state."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from nixchirp.assets.decoder import AnimationDecoder, AnimationInfo

logger = logging.getLogger(__name__)


@dataclass
class LoadedAnimation:
    """A fully loaded animation ready for playback."""

    info: AnimationInfo
    frames: list[np.ndarray]
    frame_duration_ms: float  # Duration per frame based on FPS

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def get_frame(self, index: int) -> np.ndarray:
        """Get a frame by index, wrapping around for looping."""
        return self.frames[index % self.frame_count]


def load_animation(path: str | Path) -> LoadedAnimation:
    """Load an animation file, decoding all frames into memory.

    Args:
        path: Path to a GIF, APNG, WebM, or MP4 file.

    Returns:
        LoadedAnimation with all frames decoded as RGBA arrays.
    """
    path = Path(path)
    logger.info("Loading animation: %s", path)

    with AnimationDecoder(path) as decoder:
        info = decoder.info
        assert info is not None
        frames = decoder.decode_all_frames()

    if not frames:
        raise ValueError(f"No frames decoded from {path}")

    frame_duration_ms = 1000.0 / info.fps if info.fps > 0 else 33.33

    logger.info(
        "Loaded %d frames (%dx%d) at %.1f FPS from %s",
        len(frames), info.width, info.height, info.fps, path.name,
    )

    return LoadedAnimation(
        info=info,
        frames=frames,
        frame_duration_ms=frame_duration_ms,
    )
