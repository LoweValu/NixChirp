"""Transition logic between states (cut, crossfade)."""

from __future__ import annotations

import time
from enum import Enum, auto


class TransitionType(Enum):
    CUT = auto()
    CROSSFADE = auto()


def parse_transition_type(name: str) -> TransitionType:
    """Parse a transition type string from config."""
    name = name.lower().strip()
    if name == "crossfade":
        return TransitionType.CROSSFADE
    return TransitionType.CUT


class Transition:
    """Manages an in-progress transition between two states.

    For CUT transitions, completes instantly.
    For CROSSFADE, tracks blend progress over duration_ms.
    """

    def __init__(
        self,
        transition_type: TransitionType,
        duration_ms: int = 80,
    ) -> None:
        self.transition_type = transition_type
        self.duration_ms = max(1, duration_ms)
        self._start_time: float = 0.0
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def blend(self) -> float:
        """Current blend factor: 0.0 = fully old state, 1.0 = fully new state."""
        if not self._active or self.transition_type == TransitionType.CUT:
            return 1.0
        elapsed_ms = (time.monotonic() - self._start_time) * 1000.0
        t = min(1.0, elapsed_ms / self.duration_ms)
        # Smooth step for nicer visual
        return t * t * (3.0 - 2.0 * t)

    def start(self) -> None:
        """Begin the transition."""
        if self.transition_type == TransitionType.CUT:
            self._active = False
            return
        self._start_time = time.monotonic()
        self._active = True

    def update(self) -> bool:
        """Update transition state. Returns True if still in progress."""
        if not self._active:
            return False
        elapsed_ms = (time.monotonic() - self._start_time) * 1000.0
        if elapsed_ms >= self.duration_ms:
            self._active = False
            return False
        return True

    def cancel(self) -> None:
        """Cancel the transition immediately."""
        self._active = False
