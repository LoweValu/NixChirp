"""Microphone settings GUI panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from imgui_bundle import imgui

if TYPE_CHECKING:
    from nixchirp.app import App


def draw_mic_panel(app: App) -> None:
    """Draw the microphone configuration panel."""
    mic = app._mic
    config = app.config
    sm = app._state_machine

    # Mic availability
    if not mic or not mic.available:
        imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), "Microphone unavailable")
        imgui.text("Install 'sounddevice' and ensure PortAudio is available.")
        return

    # Enable/disable
    changed, enabled = imgui.checkbox("Mic Enabled", mic.enabled)
    if changed:
        mic.enabled = enabled

    imgui.separator()

    # Real-time volume meter
    rms = mic.current_rms
    imgui.text("Volume:")
    imgui.same_line()
    imgui.progress_bar(min(rms * 5.0, 1.0), imgui.ImVec2(-1, 0), f"{rms:.3f}")

    # Status
    imgui.text("Status:")
    imgui.same_line()
    if mic.is_active:
        imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), "Speaking")
    else:
        imgui.text("Silent")

    imgui.spacing()
    imgui.separator()
    imgui.text("Thresholds")
    imgui.spacing()

    # Open threshold
    changed, val = imgui.slider_float(
        "Open threshold", config.mic.open_threshold, 0.001, 0.5, "%.3f"
    )
    if changed:
        config.mic.open_threshold = val
        mic._open_threshold = val

    # Close threshold
    changed, val = imgui.slider_float(
        "Close threshold", config.mic.close_threshold, 0.001, 0.5, "%.3f"
    )
    if changed:
        config.mic.close_threshold = val
        mic._close_threshold = val

    # Intense threshold
    changed, val = imgui.slider_float(
        "Intense threshold", config.mic.intense_threshold, 0.01, 1.0, "%.3f"
    )
    if changed:
        config.mic.intense_threshold = val
        mic._intense_threshold = val

    # Hold time
    changed, val = imgui.slider_int(
        "Hold time (ms)", config.mic.hold_time_ms, 0, 1000
    )
    if changed:
        config.mic.hold_time_ms = val
        mic._hold_time_s = val / 1000.0

    imgui.spacing()

    # Device info
    if imgui.collapsing_header("Audio Devices"):
        devices = mic.list_devices()
        if devices:
            for d in devices:
                imgui.bullet_text(f"[{d['index']}] {d['name']} ({d['channels']}ch)")
        else:
            imgui.text("No input devices found")
