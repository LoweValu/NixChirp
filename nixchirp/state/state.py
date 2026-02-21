"""State dataclass representing a visual avatar state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class State:
    """A single visual state of the avatar (e.g., 'idle', 'talking', 'happy').

    Each state maps to an animation file and has playback properties.
    """

    name: str
    file: str
    loop: bool = True
    speed: float = 1.0
    group: str = ""
    transition_in: str = "cut"
    transition_in_duration_ms: int = 80
    transition_out: str = "cut"
    transition_out_duration_ms: int = 80

    @property
    def file_path(self) -> Path:
        return Path(self.file)
