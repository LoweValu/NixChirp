"""States management GUI panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from imgui_bundle import imgui

if TYPE_CHECKING:
    from nixchirp.app import App


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
            # Name
            changed, new_name = imgui.input_text("Name", sc.name)
            if changed:
                # Update state machine too
                old_name = sc.name
                sc.name = new_name
                state = sm.get_state(old_name)
                if state:
                    state.name = new_name
                    # Update references
                    sm._states.pop(old_name, None)
                    sm._states[new_name] = state
                    if config.mic.idle_state == old_name:
                        config.mic.idle_state = new_name
                        sm.mic_idle_state = new_name
                    if config.mic.active_state == old_name:
                        config.mic.active_state = new_name
                        sm.mic_active_state = new_name

            # File path
            changed, new_file = imgui.input_text("File", sc.file)
            if changed:
                sc.file = new_file
                state = sm.get_state(sc.name)
                if state:
                    state.file = new_file

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
        # Remove from state machine
        sm._states.pop(removed.name, None)

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
