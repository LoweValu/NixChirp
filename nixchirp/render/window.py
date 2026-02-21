"""SDL2 window creation and management."""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import sdl2
import sdl2.ext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_ICON_PKG = "nixchirp.data.icons.hicolor.256x256.apps"
_ICON_NAME = "io.github.nixchirp.NixChirp.png"

from nixchirp.constants import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_TITLE,
    DEFAULT_WINDOW_WIDTH,
    OUTPUT_CHROMA,
    OUTPUT_TRANSPARENT,
)


class Window:
    """SDL2 window with OpenGL context."""

    def __init__(
        self,
        title: str = DEFAULT_WINDOW_TITLE,
        width: int = DEFAULT_WINDOW_WIDTH,
        height: int = DEFAULT_WINDOW_HEIGHT,
        output_mode: str = "windowed",
    ) -> None:
        self.title = title
        self.width = width
        self.height = height
        self.output_mode = output_mode
        self._window: ctypes.c_void_p | None = None
        self._gl_context: ctypes.c_void_p | None = None
        self._running = False

    def create(self) -> None:
        """Initialize SDL2 and create the window with an OpenGL context."""
        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_EVENTS) != 0:
            raise RuntimeError(f"SDL2 init failed: {sdl2.SDL_GetError().decode()}")

        # Request OpenGL 3.3 core profile
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 3)
        sdl2.SDL_GL_SetAttribute(
            sdl2.SDL_GL_CONTEXT_PROFILE_MASK,
            sdl2.SDL_GL_CONTEXT_PROFILE_CORE,
        )
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_DOUBLEBUFFER, 1)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_DEPTH_SIZE, 0)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_STENCIL_SIZE, 0)

        flags = sdl2.SDL_WINDOW_OPENGL | sdl2.SDL_WINDOW_SHOWN | sdl2.SDL_WINDOW_RESIZABLE

        if self.output_mode == OUTPUT_TRANSPARENT:
            # Request ARGB visual for transparent window
            sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_ALPHA_SIZE, 8)
            flags |= sdl2.SDL_WINDOW_BORDERLESS

        self._window = sdl2.SDL_CreateWindow(
            self.title.encode("utf-8"),
            sdl2.SDL_WINDOWPOS_CENTERED,
            sdl2.SDL_WINDOWPOS_CENTERED,
            self.width,
            self.height,
            flags,
        )
        if not self._window:
            raise RuntimeError(f"Failed to create window: {sdl2.SDL_GetError().decode()}")

        self._gl_context = sdl2.SDL_GL_CreateContext(self._window)
        if not self._gl_context:
            raise RuntimeError(f"Failed to create GL context: {sdl2.SDL_GetError().decode()}")

        # Enable vsync (adaptive if available, else standard)
        if sdl2.SDL_GL_SetSwapInterval(-1) == -1:
            sdl2.SDL_GL_SetSwapInterval(1)

        # Set window icon
        self._set_icon()

        self._running = True

    def _set_icon(self) -> None:
        """Load and set the window icon from bundled package data."""
        try:
            from importlib import resources
            from PIL import Image
            import io

            icon_data = resources.files(_ICON_PKG).joinpath(_ICON_NAME).read_bytes()
            img = Image.open(io.BytesIO(icon_data)).convert("RGBA")
            w, h = img.size
            pixels = img.tobytes()
            # Create SDL surface from raw RGBA pixels
            surface = sdl2.SDL_CreateRGBSurfaceWithFormatFrom(
                pixels, w, h, 32, w * 4, sdl2.SDL_PIXELFORMAT_RGBA32
            )
            if surface:
                sdl2.SDL_SetWindowIcon(self._window, surface)
                sdl2.SDL_FreeSurface(surface)
                logger.debug("Window icon set from package data")
        except Exception:
            logger.debug("Failed to set window icon", exc_info=True)

    def swap(self) -> None:
        """Swap the GL buffer to present the frame."""
        if self._window:
            sdl2.SDL_GL_SwapWindow(self._window)

    def get_size(self) -> tuple[int, int]:
        """Get the current drawable size in pixels."""
        w = ctypes.c_int()
        h = ctypes.c_int()
        if self._window:
            sdl2.SDL_GL_GetDrawableSize(self._window, ctypes.byref(w), ctypes.byref(h))
        return w.value, h.value

    def set_title(self, title: str) -> None:
        """Update the window title."""
        if self._window:
            sdl2.SDL_SetWindowTitle(self._window, title.encode("utf-8"))

    @property
    def running(self) -> bool:
        return self._running

    def poll_events(self) -> list[sdl2.SDL_Event]:
        """Poll all pending SDL events. Returns the list and sets running=False on quit."""
        events = []
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == sdl2.SDL_QUIT:
                self._running = False
            events.append(event)
            event = sdl2.SDL_Event()
        return events

    def destroy(self) -> None:
        """Clean up SDL2 resources."""
        if self._gl_context:
            sdl2.SDL_GL_DeleteContext(self._gl_context)
            self._gl_context = None
        if self._window:
            sdl2.SDL_DestroyWindow(self._window)
            self._window = None
        sdl2.SDL_Quit()
        self._running = False
