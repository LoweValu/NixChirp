"""Sleep timer — transitions the avatar to a sleep state after inactivity."""

from __future__ import annotations

import logging
from enum import Enum, auto

logger = logging.getLogger(__name__)


class SleepEvent(Enum):
    """Events emitted by the sleep timer."""

    FELL_ASLEEP = auto()
    WOKE_UP = auto()


class SleepTimer:
    """Tracks input activity and triggers sleep/wake transitions.

    Not a background thread — call :meth:`update` each frame from the main
    loop.  Call :meth:`activity` whenever any input source is active (mic
    speaking, MIDI event, hotkey press).

    Args:
        timeout_seconds: Seconds of inactivity before sleeping.
                         0 or negative disables the timer.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = max(0.0, float(timeout_seconds))
        self._elapsed: float = 0.0
        self._sleeping = False
        self._enabled = self._timeout > 0

    @property
    def sleeping(self) -> bool:
        return self._sleeping

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = max(0.0, float(value))
        self._enabled = self._timeout > 0
        if not self._enabled and self._sleeping:
            # Disabling while asleep → wake up
            self._sleeping = False
            self._elapsed = 0.0

    def activity(self) -> None:
        """Signal that input activity occurred — resets the inactivity timer."""
        self._elapsed = 0.0

    def update(self, dt: float) -> SleepEvent | None:
        """Tick the timer.  Returns an event if the sleep state changed.

        Args:
            dt: Time delta in seconds since last frame.

        Returns:
            ``SleepEvent.FELL_ASLEEP`` when transitioning to sleep,
            ``SleepEvent.WOKE_UP`` when waking (after :meth:`activity`),
            or ``None`` if no change.
        """
        if not self._enabled:
            return None

        if self._sleeping:
            # Already asleep — check if activity() was called (elapsed was reset)
            if self._elapsed == 0.0:
                self._sleeping = False
                logger.info("Sleep timer: woke up")
                return SleepEvent.WOKE_UP
            return None

        # Awake — accumulate inactivity
        self._elapsed += dt
        if self._elapsed >= self._timeout:
            self._sleeping = True
            logger.info("Sleep timer: fell asleep after %.0fs", self._timeout)
            return SleepEvent.FELL_ASLEEP

        return None
