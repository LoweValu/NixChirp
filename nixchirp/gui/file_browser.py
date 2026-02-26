"""Simple ImGui file browser for selecting avatar files."""

from __future__ import annotations

import os
from pathlib import Path

from imgui_bundle import imgui

_EXTENSIONS = {".gif", ".apng", ".png", ".webm"}


class FileBrowser:
    """Minimal ImGui file browser that returns real filesystem paths."""

    def __init__(self) -> None:
        self._open = False
        self._current_dir = Path.home()
        self._result: str | None = None
        self._done = False
        self._target_idx: int = -1

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self, target_idx: int, starting_dir: str = "") -> None:
        """Open the file browser for a given state index."""
        self._open = True
        self._done = False
        self._result = None
        self._target_idx = target_idx
        if starting_dir:
            p = Path(starting_dir)
            # If starting_dir is a file, use its parent
            if p.is_file():
                p = p.parent
            if p.is_dir():
                self._current_dir = p
                return
        self._current_dir = Path.home()

    def poll(self) -> tuple[int, str | None] | None:
        """Return (target_idx, path) if done, None if still open."""
        if self._done:
            result = (self._target_idx, self._result)
            self._open = False
            self._done = False
            return result
        return None

    def draw(self) -> None:
        """Render the file browser window. Call every frame."""
        if not self._open:
            return

        imgui.set_next_window_size(imgui.ImVec2(550, 450), imgui.Cond_.first_use_ever.value)
        _, opened = imgui.begin("Select Avatar File##filebrowser", True)
        if not opened:
            self._done = True
            imgui.end()
            return

        # Current directory path (editable)
        changed, new_path = imgui.input_text("##dir", str(self._current_dir))
        if changed:
            p = Path(new_path)
            if p.is_dir():
                self._current_dir = p

        imgui.separator()

        # File list
        imgui.begin_child("##filelist", imgui.ImVec2(0, -30))
        try:
            entries = sorted(
                self._current_dir.iterdir(),
                key=lambda e: (not e.is_dir(), e.name.lower()),
            )
        except PermissionError:
            entries = []
            imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), "Permission denied")

        # Parent directory
        if self._current_dir.parent != self._current_dir:
            if imgui.selectable("..##parent", False)[0]:
                self._current_dir = self._current_dir.parent

        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                if imgui.selectable(f"[{entry.name}]", False)[0]:
                    self._current_dir = entry
            elif entry.suffix.lower() in _EXTENSIONS:
                if imgui.selectable(entry.name, False)[0]:
                    self._result = str(entry)
                    self._done = True

        imgui.end_child()

        # Cancel button
        if imgui.button("Cancel"):
            self._done = True

        imgui.end()
