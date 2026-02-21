"""Audio analysis helpers — RMS, peak, noise gate."""

from __future__ import annotations

import numpy as np


def compute_rms(samples: np.ndarray) -> float:
    """Compute Root Mean Square of audio samples.

    Args:
        samples: Audio samples as float32 array (mono or multi-channel).

    Returns:
        RMS value in range [0.0, 1.0] for normalized audio.
    """
    if samples.size == 0:
        return 0.0
    # If multi-channel, average channels
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return float(np.sqrt(np.mean(samples ** 2)))


def compute_peak(samples: np.ndarray) -> float:
    """Compute peak amplitude of audio samples.

    Args:
        samples: Audio samples as float32 array.

    Returns:
        Peak value in range [0.0, 1.0] for normalized audio.
    """
    if samples.size == 0:
        return 0.0
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    return float(np.max(np.abs(samples)))
