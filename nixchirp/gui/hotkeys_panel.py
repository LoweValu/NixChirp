"""Global hotkey mapping GUI panel (XDG Desktop Portal)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from imgui_bundle import imgui

if TYPE_CHECKING:
    from nixchirp.app import App

logger = logging.getLogger(__name__)


def draw_hotkeys_panel(app: App) -> None:
    """Draw the hotkeys configuration panel."""
    hotkey_input = app._hotkeys
    config = app.config

    # --- Portal status ---
    if hotkey_input is None:
        imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), "Hotkey system not initialized")
        return

    if not hotkey_input.available:
        imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), "dbus-fast not installed")
        imgui.text("Install: pip install dbus-fast")
        return

    status = hotkey_input.status
    if status == "Active":
        imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), "Global shortcuts active")
    elif status == "Connected":
        imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), "Portal connected")
    elif status == "Portal not available":
        imgui.text_colored(imgui.ImVec4(1.0, 0.8, 0.3, 1.0), "GlobalShortcuts portal not available")
        imgui.text("Your desktop may not support this feature.")
        imgui.text("Requires KDE Plasma 5.27+ or GNOME 44+.")
    elif "denied" in status.lower() or "failed" in status.lower():
        imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), status)
    else:
        imgui.text_colored(imgui.ImVec4(1.0, 0.8, 0.3, 1.0), status)

    imgui.spacing()
    imgui.separator()
    imgui.text("Hotkey Mappings")
    imgui.spacing()

    state_names = app._state_machine.state_names
    group_names = list(app._state_groups.keys())
    actions = ["set_group", "set_state"]
    action_labels = ["Set Group", "Set State"]

    # Mapping table
    remove_idx = -1
    any_changed = False
    for i, hk in enumerate(config.hotkeys):
        imgui.push_id(f"hk_{i}")

        # Show bound trigger (read-only, set by portal)
        if i < len(hotkey_input.mappings) and hotkey_input.mappings[i].trigger:
            trigger = hotkey_input.mappings[i].trigger
            imgui.text_colored(imgui.ImVec4(0.7, 0.9, 1.0, 1.0), f"Bound: {trigger}")
        else:
            imgui.text_colored(imgui.ImVec4(0.6, 0.6, 0.6, 1.0), "Not bound yet")

        # Action
        act_idx = actions.index(hk.action) if hk.action in actions else 0
        changed, new_idx = imgui.combo("Action", act_idx, action_labels)
        if changed:
            hk.action = actions[new_idx]
            any_changed = True

        # Target (depends on action)
        if hk.action == "set_group":
            target_names = ["(none)"] + group_names
            t_idx = target_names.index(hk.target) if hk.target in target_names else 0
            changed, new_idx = imgui.combo("Target Group", t_idx, target_names)
            if changed:
                hk.target = target_names[new_idx] if new_idx > 0 else ""
                any_changed = True
            if not group_names:
                imgui.text_colored(
                    imgui.ImVec4(1.0, 0.8, 0.3, 1.0),
                    "Define groups in the Mic tab first",
                )
        elif hk.action == "set_state":
            target_names = ["(none)"] + state_names
            t_idx = target_names.index(hk.target) if hk.target in target_names else 0
            changed, new_idx = imgui.combo("Target State", t_idx, target_names)
            if changed:
                hk.target = target_names[new_idx] if new_idx > 0 else ""
                any_changed = True

        imgui.same_line()
        if imgui.button("Remove"):
            remove_idx = i

        imgui.separator()
        imgui.pop_id()

    if remove_idx >= 0:
        config.hotkeys.pop(remove_idx)
        any_changed = True

    imgui.spacing()
    if imgui.button("+ Add Hotkey"):
        from nixchirp.config import HotkeyConfig
        config.hotkeys.append(HotkeyConfig())
        any_changed = True

    if any_changed:
        _sync_mappings_to_hotkeys(app)

    # Bind button — sends shortcuts to the portal (shows system dialog)
    imgui.spacing()
    imgui.spacing()
    can_bind = hotkey_input.session_active and len(config.hotkeys) > 0
    if can_bind:
        if imgui.button("Bind Shortcuts"):
            hotkey_input.bind_shortcuts()
            imgui.text("System dialog should appear...")
    elif not hotkey_input.session_active:
        imgui.text_colored(
            imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
            "Waiting for portal session...",
        )


def _sync_mappings_to_hotkeys(app: App) -> None:
    """Sync config hotkey mappings to the HotkeyInput's runtime mapping list."""
    if not app._hotkeys:
        return
    from nixchirp.input.hotkeys import HotkeyMapping
    app._hotkeys.mappings = [
        HotkeyMapping(
            action=h.action,
            target=h.target,
        )
        for h in app.config.hotkeys
    ]
