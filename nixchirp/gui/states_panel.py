"""States management GUI panel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from imgui_bundle import imgui

from nixchirp.gui.file_browser import FileBrowser

if TYPE_CHECKING:
    from nixchirp.app import App

logger = logging.getLogger(__name__)

# --- Editing state ---
# Decoupled name buffer: only exists while a Name field is being edited.
# Keeps sc.name (and thus the collapsing header) stable during typing.
_name_buffers: dict[int, str] = {}
_name_originals: dict[int, str] = {}

# Shared file browser instance
_file_browser = FileBrowser()


def _commit_rename(app: App, idx: int, old_name: str, new_name: str) -> None:
    """Commit a state rename: update state machine dict and all references."""
    if old_name == new_name or not new_name:
        return
    sm = app._state_machine
    config = app.config
    sc = config.states[idx]
    sc.name = new_name
    state = sm.get_state(old_name)
    if not state:
        return
    state.name = new_name
    sm._states.pop(old_name, None)
    sm._states[new_name] = state
    # Update mic references
    if config.mic.idle_state == old_name:
        config.mic.idle_state = new_name
        sm.mic_idle_state = new_name
    if config.mic.active_state == old_name:
        config.mic.active_state = new_name
        sm.mic_active_state = new_name
    if config.mic.intense_state == old_name:
        config.mic.intense_state = new_name
        sm.mic_intense_state = new_name
    # Update sleep state reference
    if config.general.sleep_state == old_name:
        config.general.sleep_state = new_name
    # Update state group references
    for sg in config.state_groups:
        if sg.idle_state == old_name:
            sg.idle_state = new_name
        if sg.active_state == old_name:
            sg.active_state = new_name
        if sg.intense_state == old_name:
            sg.intense_state = new_name


def draw_states_panel(app: App) -> None:
    """Draw the states configuration panel."""
    sm = app._state_machine
    config = app.config
    current = sm.current_state

    imgui.text("Active state:")
    imgui.same_line()
    if current:
        imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), current.name)
    else:
        imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), "None")

    imgui.separator()
    imgui.text("Configured States:")
    imgui.spacing()

    remove_idx = -1
    for i, sc in enumerate(config.states):
        imgui.push_id(f"state_{i}")

        # Highlight active state
        is_active = current and current.name == sc.name
        if is_active:
            imgui.push_style_color(imgui.Col_.text.value, imgui.ImVec4(0.4, 1.0, 0.4, 1.0))

        expanded = imgui.collapsing_header(f"{sc.name}##hdr")

        if is_active:
            imgui.pop_style_color()

        if expanded:
            # Name — fully decoupled buffer: sc.name stays unchanged during editing
            buf = _name_buffers.get(i, sc.name)
            changed, new_buf = imgui.input_text("Name", buf)
            if imgui.is_item_activated():
                _name_buffers[i] = sc.name
                _name_originals[i] = sc.name
            if changed:
                _name_buffers[i] = new_buf
            if imgui.is_item_deactivated_after_edit():
                old_name = _name_originals.pop(i, sc.name)
                final_name = _name_buffers.pop(i, new_buf)
                _commit_rename(app, i, old_name, final_name)
            elif imgui.is_item_deactivated():
                # Cancelled — discard buffer
                _name_buffers.pop(i, None)
                _name_originals.pop(i, None)

            # File path with Browse button
            imgui.set_next_item_width(imgui.get_content_region_avail().x - 80)
            changed, new_file = imgui.input_text("##file", sc.file)
            if changed:
                sc.file = new_file
                state = sm.get_state(sc.name)
                if state:
                    state.file = new_file
            imgui.same_line()
            if imgui.button("Browse..."):
                _file_browser.open(i, sc.file)

            # Loop
            changed, new_loop = imgui.checkbox("Loop", sc.loop)
            if changed:
                sc.loop = new_loop
                state = sm.get_state(sc.name)
                if state:
                    state.loop = new_loop

            # Speed
            changed, new_speed = imgui.slider_float("Speed", sc.speed, 0.1, 5.0, "%.1fx")
            if changed:
                sc.speed = new_speed
                state = sm.get_state(sc.name)
                if state:
                    state.speed = new_speed

            # Activate button
            if not is_active:
                if imgui.button("Activate"):
                    from nixchirp.state.machine import EventType, StateEvent
                    sm.push_event(StateEvent(EventType.SET_STATE, target_state=sc.name))

            # Remove button
            imgui.same_line()
            if imgui.button("Remove"):
                remove_idx = i

        imgui.pop_id()

    # Process removal
    if remove_idx >= 0:
        removed = config.states.pop(remove_idx)
        sm._states.pop(removed.name, None)
        _name_buffers.pop(remove_idx, None)
        _name_originals.pop(remove_idx, None)
        # If the removed state was the current state, clear it
        if current and current.name == removed.name:
            if config.states:
                first = config.states[0]
                new_state = sm.get_state(first.name)
                if new_state:
                    sm._current_state = new_state
                    app._load_state_animation(new_state)
            else:
                sm._current_state = None
                app._current_animation = None

    imgui.spacing()
    imgui.separator()

    # Add new state
    if imgui.button("+ Add State"):
        from nixchirp.config import StateConfig
        from nixchirp.state.state import State
        new_name = f"state_{len(config.states)}"
        sc = StateConfig(name=new_name, file="")
        config.states.append(sc)
        sm.add_state(State(name=new_name, file=""))

    # --- File browser (rendered outside collapsing headers) ---
    _file_browser.draw()
    result = _file_browser.poll()
    if result is not None:
        target_idx, path = result
        if path and 0 <= target_idx < len(config.states):
            sc = config.states[target_idx]
            sc.file = path
            state = sm.get_state(sc.name)
            if state:
                state.file = path

    # ===== Default Group & State Groups =====
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
