"""Output/render settings GUI panel."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from imgui_bundle import imgui

from nixchirp.constants import (
    OUTPUT_CHROMA,
    OUTPUT_TRANSPARENT,
    OUTPUT_VIRTUAL_CAM,
    OUTPUT_WINDOWED,
)
from nixchirp.render.virtual_cam import (
    find_v4l2loopback_devices,
    is_v4l2loopback_loaded,
    load_v4l2loopback,
)

if TYPE_CHECKING:
    from nixchirp.app import App

_OUTPUT_MODES = [OUTPUT_WINDOWED, OUTPUT_CHROMA, OUTPUT_TRANSPARENT, OUTPUT_VIRTUAL_CAM]
_OUTPUT_LABELS = ["Windowed", "Chroma Key", "Transparent", "Virtual Camera"]

# Module-level state for async pkexec operation
_modprobe_busy = False
_modprobe_result: str = ""


def draw_output_panel(app: App) -> None:
    """Draw the output/render settings panel."""
    global _modprobe_busy, _modprobe_result
    config = app.config

    # Output mode
    old_mode = config.output.mode
    current_idx = _OUTPUT_MODES.index(old_mode) if old_mode in _OUTPUT_MODES else 0
    changed, new_idx = imgui.combo("Output Mode", current_idx, _OUTPUT_LABELS)
    if changed:
        new_mode = _OUTPUT_MODES[new_idx]
        config.output.mode = new_mode
        _handle_mode_switch(app, old_mode, new_mode)

    imgui.spacing()

    # Chroma key color (relevant for chroma mode AND virtual cam background)
    if config.output.mode in (OUTPUT_CHROMA, OUTPUT_VIRTUAL_CAM):
        label = "Chroma Color" if config.output.mode == OUTPUT_CHROMA else "Virtual Cam BG"
        hex_color = config.output.chroma_color.lstrip("#")
        try:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
        except (ValueError, IndexError):
            r, g, b = 0.0, 1.0, 0.0
        changed, color = imgui.color_edit3(label, [r, g, b])
        if changed:
            hr = int(color[0] * 255)
            hg = int(color[1] * 255)
            hb = int(color[2] * 255)
            config.output.chroma_color = f"#{hr:02X}{hg:02X}{hb:02X}"

    # Resolution
    imgui.spacing()
    imgui.separator()
    imgui.text("Resolution")
    imgui.spacing()

    res = list(config.output.resolution)
    changed, new_w = imgui.input_int("Width", res[0], 10, 100)
    if changed and new_w > 0:
        config.output.resolution = (new_w, res[1])

    changed, new_h = imgui.input_int("Height", res[1], 10, 100)
    if changed and new_h > 0:
        config.output.resolution = (res[0], new_h)

    # FPS cap
    imgui.spacing()
    imgui.separator()
    changed, new_fps = imgui.slider_int("FPS Cap", config.general.fps_cap, 10, 120)
    if changed:
        config.general.fps_cap = new_fps
        app._fps_cap = new_fps
        app._frame_time_target = 1.0 / new_fps

    # Transition settings
    imgui.spacing()
    imgui.separator()
    imgui.text("Transitions")
    imgui.spacing()

    trans_types = ["cut", "crossfade"]
    current_trans_idx = trans_types.index(config.transitions.default_type) if config.transitions.default_type in trans_types else 0
    changed, new_idx = imgui.combo("Default Type", current_trans_idx, ["Cut", "Crossfade"])
    if changed:
        config.transitions.default_type = trans_types[new_idx]
        from nixchirp.state.transitions import parse_transition_type
        app._default_transition_type = parse_transition_type(trans_types[new_idx])

    changed, new_dur = imgui.slider_int("Duration (ms)", config.transitions.default_duration_ms, 0, 500)
    if changed:
        config.transitions.default_duration_ms = new_dur
        app._default_transition_duration = new_dur

    # --- Virtual Camera section ---
    if config.output.mode == OUTPUT_VIRTUAL_CAM:
        imgui.spacing()
        imgui.separator()
        imgui.text("Virtual Camera")
        imgui.spacing()

        module_loaded = is_v4l2loopback_loaded()
        vcam = app._virtual_cam
        vcam_active = vcam is not None and vcam.is_open

        if not module_loaded:
            # Module not loaded — offer to load it
            imgui.text_colored(
                imgui.ImVec4(1.0, 0.8, 0.3, 1.0),
                "v4l2loopback kernel module not loaded",
            )
            imgui.spacing()

            if _modprobe_busy:
                imgui.text("Loading module...")
            else:
                if imgui.button("Load v4l2loopback"):
                    _modprobe_busy = True
                    _modprobe_result = ""
                    threading.Thread(target=_run_modprobe_and_connect,
                                     args=(app,), daemon=True).start()

            if _modprobe_result:
                if _modprobe_result == "Module loaded":
                    imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), _modprobe_result)
                else:
                    imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), _modprobe_result)

        elif module_loaded and not vcam_active:
            # Module loaded but virtual cam not active
            loopback_devs = find_v4l2loopback_devices(output_only=False)

            if loopback_devs:
                # Auto-fill device
                if config.output.virtual_cam_device not in loopback_devs:
                    config.output.virtual_cam_device = loopback_devs[0]

                dev_idx = (
                    loopback_devs.index(config.output.virtual_cam_device)
                    if config.output.virtual_cam_device in loopback_devs
                    else 0
                )
                changed, new_idx = imgui.combo("Device", dev_idx, loopback_devs)
                if changed:
                    config.output.virtual_cam_device = loopback_devs[new_idx]

            # Show error from last attempt
            if vcam is not None and vcam.status not in ("Not started", "Closed"):
                imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), vcam.status)

            imgui.spacing()

            # Connect button
            if _modprobe_busy:
                imgui.text("Reloading module...")
            else:
                if imgui.button("Connect"):
                    app.close_virtual_cam()
                    app.open_virtual_cam()

                imgui.same_line()

                # Reload button (fixes exclusive_caps and other config issues)
                if imgui.button("Reload Module"):
                    _modprobe_busy = True
                    _modprobe_result = ""
                    app.close_virtual_cam()
                    threading.Thread(target=_run_modprobe_and_connect,
                                     args=(app,), daemon=True).start()

            if _modprobe_result:
                if _modprobe_result == "Module loaded":
                    imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), _modprobe_result)
                else:
                    imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), _modprobe_result)

        else:
            # Active — show device and status
            imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0),
                               f"Active: {app._virtual_cam._device}")

            if imgui.button("Disconnect"):
                app.close_virtual_cam()


def _handle_mode_switch(app: App, old_mode: str, new_mode: str) -> None:
    """Handle runtime output mode switching."""
    if old_mode == OUTPUT_VIRTUAL_CAM and new_mode != OUTPUT_VIRTUAL_CAM:
        app.close_virtual_cam()

    if new_mode == OUTPUT_VIRTUAL_CAM and old_mode != OUTPUT_VIRTUAL_CAM:
        if is_v4l2loopback_loaded():
            # Auto-open if devices are available
            devs = find_v4l2loopback_devices()
            if devs:
                if app.config.output.virtual_cam_device not in devs:
                    app.config.output.virtual_cam_device = devs[0]
                app.open_virtual_cam()


def _run_modprobe() -> None:
    """Run pkexec modprobe in a background thread."""
    global _modprobe_busy, _modprobe_result
    try:
        ok, msg = load_v4l2loopback()
        _modprobe_result = msg
    except Exception as e:
        _modprobe_result = str(e)
    finally:
        _modprobe_busy = False


def _run_modprobe_and_connect(app: App) -> None:
    """Reload v4l2loopback and auto-connect in a background thread."""
    global _modprobe_busy, _modprobe_result
    try:
        ok, msg = load_v4l2loopback()
        _modprobe_result = msg
        if ok:
            # Give the kernel a moment to create the new devices
            import time
            time.sleep(0.5)
            # Auto-detect and connect
            devs = find_v4l2loopback_devices()
            if devs:
                app.config.output.virtual_cam_device = devs[0]
                app.open_virtual_cam()
    except Exception as e:
        _modprobe_result = str(e)
    finally:
        _modprobe_busy = False
