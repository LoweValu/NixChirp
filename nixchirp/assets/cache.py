"""LRU frame cache for decoded animation frames."""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

import numpy as np

from nixchirp.assets.loader import LoadedAnimation, load_animation
from nixchirp.constants import DEFAULT_CACHE_MAX_MB

logger = logging.getLogger(__name__)


class FrameCache:
    """LRU cache for loaded animations, bounded by total memory usage.

    Caches entire decoded animations (all frames). When the cache exceeds
    the memory budget, the least-recently-used animation is evicted.
    """

    def __init__(self, max_mb: int = DEFAULT_CACHE_MAX_MB) -> None:
        self._max_bytes = max_mb * 1024 * 1024
        self._cache: OrderedDict[str, LoadedAnimation] = OrderedDict()
        self._sizes: dict[str, int] = {}  # path -> size in bytes
        self._current_bytes = 0

    @property
    def current_mb(self) -> float:
        return self._current_bytes / (1024 * 1024)

    @property
    def max_mb(self) -> int:
        return self._max_bytes // (1024 * 1024)

    @property
    def entry_count(self) -> int:
        return len(self._cache)

    def get(self, path: str | Path) -> LoadedAnimation | None:
        """Get a cached animation, returning None if not cached.

        Marks the entry as recently used.
        """
        key = str(path)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def get_or_load(self, path: str | Path) -> LoadedAnimation:
        """Get a cached animation or load it from disk.

        If loading would exceed the memory budget, evicts LRU entries first.
        """
        key = str(path)

        # Check cache first
        cached = self.get(key)
        if cached is not None:
            return cached

        # Load from disk
        animation = load_animation(path)
        size = self._compute_size(animation)

        # Evict until we have room
        while self._current_bytes + size > self._max_bytes and self._cache:
            self._evict_lru()

        # Insert
        self._cache[key] = animation
        self._sizes[key] = size
        self._current_bytes += size

        logger.info(
            "Cached %s (%.1f MB). Cache: %.1f / %d MB (%d entries)",
            Path(path).name,
            size / (1024 * 1024),
            self.current_mb,
            self.max_mb,
            self.entry_count,
        )
        return animation

    def evict(self, path: str | Path) -> None:
        """Explicitly remove an animation from the cache."""
        key = str(path)
        if key in self._cache:
            self._current_bytes -= self._sizes.pop(key, 0)
            del self._cache[key]

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._cache.clear()
        self._sizes.clear()
        self._current_bytes = 0

    def _evict_lru(self) -> None:
        """Evict the least recently used entry."""
        if not self._cache:
            return
        key, animation = self._cache.popitem(last=False)
        size = self._sizes.pop(key, 0)
        self._current_bytes -= size
        logger.info("Evicted %s (%.1f MB) from cache", Path(key).name, size / (1024 * 1024))

    @staticmethod
    def _compute_size(animation: LoadedAnimation) -> int:
        """Compute approximate memory usage of an animation in bytes."""
        total = 0
        for frame in animation.frames:
            total += frame.nbytes
        return total
