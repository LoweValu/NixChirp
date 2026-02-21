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
    imgui.separator()
    imgui.text("Default Group (fallback states)")
    imgui.spacing()

    state_names = ["(none)"] + sm.state_names

    # Idle state (mouth closed)
    current_idle_idx = 0
    if config.mic.idle_state in state_names:
        current_idle_idx = state_names.index(config.mic.idle_state)
    changed, new_idx = imgui.combo("Idle state", current_idle_idx, state_names)
    if changed:
        name = state_names[new_idx] if new_idx > 0 else ""
        config.mic.idle_state = name
        sm.mic_idle_state = name

    # Active state (mouth open)
    current_active_idx = 0
    if config.mic.active_state in state_names:
        current_active_idx = state_names.index(config.mic.active_state)
    changed, new_idx = imgui.combo("Active state", current_active_idx, state_names)
    if changed:
        name = state_names[new_idx] if new_idx > 0 else ""
        config.mic.active_state = name
        sm.mic_active_state = name

    # Intense state
    current_intense_idx = 0
    if config.mic.intense_state in state_names:
        current_intense_idx = state_names.index(config.mic.intense_state)
    changed, new_idx = imgui.combo("Intense state", current_intense_idx, state_names)
    if changed:
        name = state_names[new_idx] if new_idx > 0 else ""
        config.mic.intense_state = name
        sm.mic_intense_state = name

    imgui.spacing()
    imgui.separator()

    # State groups section
    if imgui.collapsing_header("State Groups"):
        imgui.text_wrapped(
            "State groups let MIDI switch between sets of mic-reactive states. "
            "The default group uses the assignments above."
        )
        imgui.spacing()

        # Active group display
        active = app._active_group
        if active:
            imgui.text("Active group:")
            imgui.same_line()
            imgui.text_colored(imgui.ImVec4(0.4, 0.8, 1.0, 1.0), active)
        else:
            imgui.text("Active group: default")

        imgui.spacing()

        remove_group_idx = -1
        for gi, sg in enumerate(config.state_groups):
            imgui.push_id(f"sg_{gi}")

            # Group name
            changed, new_name = imgui.input_text("Name", sg.name)
            if changed:
                old_name = sg.name
                sg.name = new_name
                # Update the app's runtime group dict
                if old_name in app._state_groups:
                    del app._state_groups[old_name]
                if new_name:
                    app._state_groups[new_name] = (sg.idle_state, sg.active_state, sg.intense_state)

            # Idle state for this group
            g_idle_idx = 0
            if sg.idle_state in state_names:
                g_idle_idx = state_names.index(sg.idle_state)
            changed, new_idx = imgui.combo("Idle", g_idle_idx, state_names)
            if changed:
                sg.idle_state = state_names[new_idx] if new_idx > 0 else ""
                if sg.name in app._state_groups:
                    app._state_groups[sg.name] = (sg.idle_state, sg.active_state, sg.intense_state)

            # Active state for this group
            g_active_idx = 0
            if sg.active_state in state_names:
                g_active_idx = state_names.index(sg.active_state)
            changed, new_idx = imgui.combo("Active", g_active_idx, state_names)
            if changed:
                sg.active_state = state_names[new_idx] if new_idx > 0 else ""
                if sg.name in app._state_groups:
                    app._state_groups[sg.name] = (sg.idle_state, sg.active_state, sg.intense_state)

            # Intense state for this group
            g_intense_idx = 0
            if sg.intense_state in state_names:
                g_intense_idx = state_names.index(sg.intense_state)
            changed, new_idx = imgui.combo("Intense", g_intense_idx, state_names)
            if changed:
                sg.intense_state = state_names[new_idx] if new_idx > 0 else ""
                if sg.name in app._state_groups:
                    app._state_groups[sg.name] = (sg.idle_state, sg.active_state, sg.intense_state)

            if imgui.button("Remove Group"):
                remove_group_idx = gi

            imgui.separator()
            imgui.pop_id()

        if remove_group_idx >= 0:
            removed = config.state_groups.pop(remove_group_idx)
            if removed.name in app._state_groups:
                del app._state_groups[removed.name]

        if imgui.button("+ Add Group"):
            from nixchirp.config import StateGroupConfig
            config.state_groups.append(StateGroupConfig())

    imgui.spacing()

    # Device info
    if imgui.collapsing_header("Audio Devices"):
        devices = mic.list_devices()
        if devices:
            for d in devices:
                imgui.bullet_text(f"[{d['index']}] {d['name']} ({d['channels']}ch)")
        else:
            imgui.text("No input devices found")
