"""Dear ImGui overlay — main GUI frame with tabbed panels."""

from __future__ import annotations

from typing import TYPE_CHECKING

from imgui_bundle import imgui

from nixchirp.gui.general_panel import draw_general_panel, update_general_timer
from nixchirp.gui.hotkeys_panel import draw_hotkeys_panel
from nixchirp.gui.mic_panel import draw_mic_panel
from nixchirp.gui.midi_panel import draw_midi_panel
from nixchirp.gui.output_panel import draw_output_panel
from nixchirp.gui.states_panel import draw_states_panel

if TYPE_CHECKING:
    from nixchirp.app import App


def draw_overlay(app: App, dt: float) -> None:
    """Draw the full configuration overlay.

    Args:
        app: The main App instance.
        dt: Time delta since last frame.
    """
    update_general_timer(dt)

    # Set up a window that covers part of the screen
    viewport = imgui.get_main_viewport()
    panel_width = min(420, viewport.size.x * 0.9)
    panel_height = min(viewport.size.y * 0.85, 800)

    imgui.set_next_window_pos(
        imgui.ImVec2(10, 10),
        imgui.Cond_.first_use_ever.value,
    )
    imgui.set_next_window_size(
        imgui.ImVec2(panel_width, panel_height),
        imgui.Cond_.first_use_ever.value,
    )

    flags = (
        imgui.WindowFlags_.no_collapse.value
    )

    expanded, opened = imgui.begin("NixChirp Settings", True, flags)

    if not opened:
        # User closed the window — hide the overlay
        imgui.end()
        app._gui_visible = False
        return

    if expanded:
        # First-run welcome message
        if not app.config.states:
            imgui.spacing()
            imgui.text_colored(imgui.ImVec4(0.4, 0.8, 1.0, 1.0), "Welcome to NixChirp!")
            imgui.text("Add avatar states in the States tab to get started.")
            imgui.text("Then assign idle/speaking states in the Mic tab.")
            imgui.spacing()
            imgui.separator()
            imgui.spacing()

        if imgui.begin_tab_bar("SettingsTabs"):
            if imgui.begin_tab_item("States")[0]:
                draw_states_panel(app)
                imgui.end_tab_item()

            if imgui.begin_tab_item("Mic")[0]:
                draw_mic_panel(app)
                imgui.end_tab_item()

            if imgui.begin_tab_item("MIDI")[0]:
                draw_midi_panel(app)
                imgui.end_tab_item()

            if imgui.begin_tab_item("Hotkeys")[0]:
                draw_hotkeys_panel(app)
                imgui.end_tab_item()

            if imgui.begin_tab_item("Output")[0]:
                draw_output_panel(app)
                imgui.end_tab_item()

            if imgui.begin_tab_item("General")[0]:
                draw_general_panel(app)
                imgui.end_tab_item()

            imgui.end_tab_bar()

    imgui.end()
