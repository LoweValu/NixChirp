"""Minimal SDL2 platform backend for imgui-bundle.

Bridges SDL2 events to Dear ImGui's IO system.
Uses imgui-bundle's built-in OpenGL3 renderer backend.
"""

from __future__ import annotations

import ctypes

import sdl2
from imgui_bundle import imgui

# SDL2 scancode → ImGuiKey mapping
_SCANCODE_TO_IMGUI_KEY: dict[int, int] = {
    sdl2.SDL_SCANCODE_TAB: imgui.Key.tab.value,
    sdl2.SDL_SCANCODE_LEFT: imgui.Key.left_arrow.value,
    sdl2.SDL_SCANCODE_RIGHT: imgui.Key.right_arrow.value,
    sdl2.SDL_SCANCODE_UP: imgui.Key.up_arrow.value,
    sdl2.SDL_SCANCODE_DOWN: imgui.Key.down_arrow.value,
    sdl2.SDL_SCANCODE_PAGEUP: imgui.Key.page_up.value,
    sdl2.SDL_SCANCODE_PAGEDOWN: imgui.Key.page_down.value,
    sdl2.SDL_SCANCODE_HOME: imgui.Key.home.value,
    sdl2.SDL_SCANCODE_END: imgui.Key.end.value,
    sdl2.SDL_SCANCODE_INSERT: imgui.Key.insert.value,
    sdl2.SDL_SCANCODE_DELETE: imgui.Key.delete.value,
    sdl2.SDL_SCANCODE_BACKSPACE: imgui.Key.backspace.value,
    sdl2.SDL_SCANCODE_SPACE: imgui.Key.space.value,
    sdl2.SDL_SCANCODE_RETURN: imgui.Key.enter.value,
    sdl2.SDL_SCANCODE_ESCAPE: imgui.Key.escape.value,
    sdl2.SDL_SCANCODE_A: imgui.Key.a.value,
    sdl2.SDL_SCANCODE_C: imgui.Key.c.value,
    sdl2.SDL_SCANCODE_V: imgui.Key.v.value,
    sdl2.SDL_SCANCODE_X: imgui.Key.x.value,
    sdl2.SDL_SCANCODE_Y: imgui.Key.y.value,
    sdl2.SDL_SCANCODE_Z: imgui.Key.z.value,
    sdl2.SDL_SCANCODE_F1: imgui.Key.f1.value,
    sdl2.SDL_SCANCODE_F2: imgui.Key.f2.value,
    sdl2.SDL_SCANCODE_F3: imgui.Key.f3.value,
    sdl2.SDL_SCANCODE_F4: imgui.Key.f4.value,
    sdl2.SDL_SCANCODE_F5: imgui.Key.f5.value,
    sdl2.SDL_SCANCODE_F6: imgui.Key.f6.value,
    sdl2.SDL_SCANCODE_F7: imgui.Key.f7.value,
    sdl2.SDL_SCANCODE_F8: imgui.Key.f8.value,
    sdl2.SDL_SCANCODE_F9: imgui.Key.f9.value,
    sdl2.SDL_SCANCODE_F10: imgui.Key.f10.value,
    sdl2.SDL_SCANCODE_F11: imgui.Key.f11.value,
    sdl2.SDL_SCANCODE_F12: imgui.Key.f12.value,
    sdl2.SDL_SCANCODE_LCTRL: imgui.Key.left_ctrl.value,
    sdl2.SDL_SCANCODE_RCTRL: imgui.Key.right_ctrl.value,
    sdl2.SDL_SCANCODE_LSHIFT: imgui.Key.left_shift.value,
    sdl2.SDL_SCANCODE_RSHIFT: imgui.Key.right_shift.value,
    sdl2.SDL_SCANCODE_LALT: imgui.Key.left_alt.value,
    sdl2.SDL_SCANCODE_RALT: imgui.Key.right_alt.value,
    sdl2.SDL_SCANCODE_LGUI: imgui.Key.left_super.value,
    sdl2.SDL_SCANCODE_RGUI: imgui.Key.right_super.value,
}

# Add letter keys A-Z
for i in range(26):
    sc = getattr(sdl2, f"SDL_SCANCODE_{chr(65 + i)}")
    ik = getattr(imgui.Key, chr(97 + i))  # lowercase in imgui
    _SCANCODE_TO_IMGUI_KEY[sc] = ik.value

# Add number keys 0-9
for i in range(10):
    sc = getattr(sdl2, f"SDL_SCANCODE_{i}")
    ik = getattr(imgui.Key, f"_{i}")  # imgui uses _0, _1, etc.
    _SCANCODE_TO_IMGUI_KEY[sc] = ik.value


class ImGuiSDL2:
    """Manages Dear ImGui context with SDL2 input and OpenGL3 rendering."""

    def __init__(self) -> None:
        self._ctx: imgui.ImGuiContext | None = None
        self._time: float = 0.0

    def init(self) -> None:
        """Create ImGui context and initialize the OpenGL3 renderer."""
        self._ctx = imgui.create_context()
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard.value
        # Disable imgui.ini file saving (we manage config ourselves)
        io.set_ini_filename("")

        # Initialize OpenGL3 renderer
        imgui.backends.opengl3_init("#version 330 core")

    def new_frame(self, window_w: int, window_h: int, fb_w: int, fb_h: int, dt: float) -> None:
        """Start a new ImGui frame.

        Args:
            window_w, window_h: Window size in screen coordinates.
            fb_w, fb_h: Framebuffer size in pixels (may differ on HiDPI).
            dt: Time delta since last frame in seconds.
        """
        io = imgui.get_io()
        io.display_size = imgui.ImVec2(window_w, window_h)
        if window_w > 0 and window_h > 0:
            io.display_framebuffer_scale = imgui.ImVec2(
                fb_w / window_w, fb_h / window_h
            )
        io.delta_time = dt if dt > 0 else 1.0 / 60.0

        imgui.backends.opengl3_new_frame()
        imgui.new_frame()

    def process_event(self, event: sdl2.SDL_Event) -> bool:
        """Feed an SDL2 event to ImGui. Returns True if ImGui wants to consume it."""
        io = imgui.get_io()

        if event.type == sdl2.SDL_MOUSEMOTION:
            io.add_mouse_pos_event(float(event.motion.x), float(event.motion.y))
            return io.want_capture_mouse

        if event.type in (sdl2.SDL_MOUSEBUTTONDOWN, sdl2.SDL_MOUSEBUTTONUP):
            button = event.button.button
            imgui_button = -1
            if button == sdl2.SDL_BUTTON_LEFT:
                imgui_button = 0
            elif button == sdl2.SDL_BUTTON_RIGHT:
                imgui_button = 1
            elif button == sdl2.SDL_BUTTON_MIDDLE:
                imgui_button = 2
            if imgui_button >= 0:
                is_down = event.type == sdl2.SDL_MOUSEBUTTONDOWN
                io.add_mouse_button_event(imgui_button, is_down)
            return io.want_capture_mouse

        if event.type == sdl2.SDL_MOUSEWHEEL:
            io.add_mouse_wheel_event(
                float(event.wheel.x),
                float(event.wheel.y),
            )
            return io.want_capture_mouse

        if event.type in (sdl2.SDL_KEYDOWN, sdl2.SDL_KEYUP):
            scancode = event.key.keysym.scancode
            is_down = event.type == sdl2.SDL_KEYDOWN

            # Update modifier keys
            mod = event.key.keysym.mod
            io.add_key_event(imgui.Key.mod_ctrl, bool(mod & sdl2.KMOD_CTRL))
            io.add_key_event(imgui.Key.mod_shift, bool(mod & sdl2.KMOD_SHIFT))
            io.add_key_event(imgui.Key.mod_alt, bool(mod & sdl2.KMOD_ALT))
            io.add_key_event(imgui.Key.mod_super, bool(mod & sdl2.KMOD_GUI))

            imgui_key = _SCANCODE_TO_IMGUI_KEY.get(scancode)
            if imgui_key is not None:
                io.add_key_event(imgui.Key(imgui_key), is_down)

            return io.want_capture_keyboard

        if event.type == sdl2.SDL_TEXTINPUT:
            text = event.text.text.decode("utf-8", errors="replace")
            io.add_input_characters_utf8(text)
            return io.want_text_input

        if event.type == sdl2.SDL_WINDOWEVENT:
            if event.window.event == sdl2.SDL_WINDOWEVENT_FOCUS_GAINED:
                io.add_focus_event(True)
            elif event.window.event == sdl2.SDL_WINDOWEVENT_FOCUS_LOST:
                io.add_focus_event(False)

        return False

    def render(self) -> None:
        """Render the ImGui draw data using OpenGL3."""
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())

    def shutdown(self) -> None:
        """Clean up ImGui resources."""
        imgui.backends.opengl3_shutdown()
        if self._ctx:
            imgui.destroy_context(self._ctx)
            self._ctx = None

    @property
    def want_capture_mouse(self) -> bool:
        return imgui.get_io().want_capture_mouse

    @property
    def want_capture_keyboard(self) -> bool:
        return imgui.get_io().want_capture_keyboard
