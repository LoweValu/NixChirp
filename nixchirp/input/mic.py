"""Microphone capture and voice activity detection."""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING

import numpy as np

from nixchirp.state.machine import EventType, StateEvent
from nixchirp.util.audio import compute_rms

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Try to import sounddevice; gracefully degrade if unavailable
try:
    import sounddevice as sd
    _HAS_SOUNDDEVICE = True
except (ImportError, OSError):
    _HAS_SOUNDDEVICE = False
    logger.warning("sounddevice not available — mic input disabled")


class MicInput:
    """Captures audio from microphone and detects voice activity.

    Produces MIC_ACTIVE / MIC_IDLE / MIC_INTENSE events based on
    configurable thresholds with hysteresis.

    Runs audio capture on a background thread via sounddevice's callback API.
    """

    def __init__(
        self,
        event_queue: queue.Queue[StateEvent],
        device: str | int | None = None,
        open_threshold: float = 0.08,
        close_threshold: float = 0.05,
        intense_threshold: float = 0.4,
        hold_time_ms: int = 150,
        chunk_ms: int = 20,
        sample_rate: int = 44100,
    ) -> None:
        self._event_queue = event_queue
        self._device = device if device != "default" else None
        self._open_threshold = open_threshold
        self._close_threshold = close_threshold
        self._intense_threshold = intense_threshold
        self._hold_time_s = hold_time_ms / 1000.0
        self._chunk_size = int(sample_rate * chunk_ms / 1000)
        self._sample_rate = sample_rate

        # State
        self._is_active = False
        self._is_intense = False
        self._hold_timer: float = 0.0
        self._current_rms: float = 0.0
        self._stream: sd.InputStream | None = None if _HAS_SOUNDDEVICE else None
        self._enabled = True
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return _HAS_SOUNDDEVICE

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def current_rms(self) -> float:
        return self._current_rms

    @property
    def running(self) -> bool:
        return self._stream is not None and self._stream.active

    @property
    def is_active(self) -> bool:
        return self._is_active

    def start(self) -> None:
        """Start capturing audio from the microphone."""
        if not _HAS_SOUNDDEVICE:
            logger.warning("Cannot start mic — sounddevice not available")
            return

        try:
            self._stream = sd.InputStream(
                device=self._device,
                channels=1,
                samplerate=self._sample_rate,
                blocksize=self._chunk_size,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()
            logger.info(
                "Mic started (device=%s, rate=%d, chunk=%d)",
                self._device or "default",
                self._sample_rate,
                self._chunk_size,
            )
        except Exception:
            logger.exception("Failed to start mic capture")

    def stop(self) -> None:
        """Stop capturing audio."""
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            logger.info("Mic stopped")

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        """Called by sounddevice on the audio thread for each chunk."""
        if not self._enabled:
            return

        rms = compute_rms(indata)
        self._current_rms = rms

        with self._lock:
            was_active = self._is_active
            was_intense = self._is_intense

            if rms >= self._open_threshold:
                self._is_active = True
                self._hold_timer = self._hold_time_s

                if rms >= self._intense_threshold:
                    self._is_intense = True
                else:
                    self._is_intense = False
            else:
                # Below open threshold — check hold timer
                self._is_intense = False
                if self._is_active:
                    chunk_duration = frames / self._sample_rate
                    self._hold_timer -= chunk_duration
                    if self._hold_timer <= 0:
                        self._is_active = False
                        self._hold_timer = 0.0

            # Emit events on transitions
            if self._is_intense and not was_intense:
                self._event_queue.put_nowait(
                    StateEvent(EventType.MIC_INTENSE, value=rms)
                )
            elif self._is_active and not was_active:
                self._event_queue.put_nowait(
                    StateEvent(EventType.MIC_ACTIVE, value=rms)
                )
            elif not self._is_active and was_active:
                self._event_queue.put_nowait(
                    StateEvent(EventType.MIC_IDLE, value=rms)
                )
            elif self._is_active and was_intense and not self._is_intense:
                # Dropped from intense to normal active
                self._event_queue.put_nowait(
                    StateEvent(EventType.MIC_ACTIVE, value=rms)
                )

    @staticmethod
    def list_devices() -> list[dict]:
        """List available audio input devices."""
        if not _HAS_SOUNDDEVICE:
            return []
        devices = sd.query_devices()
        inputs = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                inputs.append({"index": i, "name": d["name"], "channels": d["max_input_channels"]})
        return inputs
