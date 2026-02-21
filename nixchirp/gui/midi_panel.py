"""MIDI mapping GUI panel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from imgui_bundle import imgui

from nixchirp.config import AppConfig

if TYPE_CHECKING:
    from nixchirp.app import App

logger = logging.getLogger(__name__)

# Learn mode state
_learn_target_idx: int = -1
_learn_status: str = ""
_learn_config: AppConfig | None = None  # Reference stored during learn
_learn_needs_sync: bool = False  # Set by callback, consumed by draw


def _on_midi_learn(event: object) -> None:
    """Module-level learn callback — uses _learn_target_idx to route."""
    global _learn_target_idx, _learn_status, _learn_config, _learn_needs_sync
    if _learn_config is None or _learn_target_idx < 0:
        return
    if _learn_target_idx >= len(_learn_config.midi_mappings):
        _learn_target_idx = -1
        return
    m = _learn_config.midi_mappings[_learn_target_idx]
    type_map = {
        "NOTE_ON": "note_on",
        "NOTE_OFF": "note_off",
        "CONTROL_CHANGE": "cc",
        "PROGRAM_CHANGE": "program_change",
    }
    m.event_type = type_map.get(event.event_type.name, "note_on")
    m.channel = event.channel
    m.note = event.note
    m.device = event.port_name
    _learn_status = f"Learned: {event.event_type.name} ch={event.channel} note={event.note}"
    _learn_target_idx = -1
    _learn_needs_sync = True


def draw_midi_panel(app: App) -> None:
    """Draw the MIDI configuration panel."""
    global _learn_target_idx, _learn_status, _learn_config, _learn_needs_sync

    midi = app._midi
    config = app.config

    # Sync runtime mappings after learn completes (callback fires on MIDI thread)
    if _learn_needs_sync:
        _learn_needs_sync = False
        _sync_mappings_to_midi(app)

    if not midi or not midi.available:
        imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.4, 1.0), "MIDI unavailable")
        imgui.text("Install 'alsa-midi' and ensure ALSA sequencer is accessible.")
        return

    # Connection status
    connected = midi.connected_ports
    if connected:
        imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), f"Connected to {len(connected)} port(s)")
    else:
        imgui.text("No MIDI ports connected")

    if imgui.button("Refresh Ports"):
        midi._connect_all_ports()

    imgui.separator()
    imgui.spacing()

    # Connected ports list
    if imgui.collapsing_header("Connected Ports"):
        if connected:
            for name in connected:
                imgui.bullet_text(name)
        else:
            imgui.text("No ports connected")
        imgui.spacing()
        # Available ports
        imgui.text("Available ports:")
        ports = midi.list_ports()
        if ports:
            for p in ports:
                imgui.bullet_text(f"[{p['client_id']}:{p['port_id']}] {p['client_name']}:{p['name']}")
        else:
            imgui.text("None found")

    imgui.spacing()
    imgui.separator()
    imgui.text("MIDI Mappings")
    imgui.spacing()

    # Learn mode status
    if midi.learn_mode:
        imgui.text_colored(imgui.ImVec4(1.0, 1.0, 0.0, 1.0), "LEARN MODE: Press a MIDI button/key...")
        if imgui.button("Cancel Learn"):
            midi.cancel_learn()
            _learn_target_idx = -1
    elif _learn_status:
        imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), _learn_status)

    imgui.spacing()

    # Active group indicator
    active_group = app._active_group
    if active_group:
        imgui.text("Active group:")
        imgui.same_line()
        imgui.text_colored(imgui.ImVec4(0.4, 0.8, 1.0, 1.0), active_group)
    else:
        imgui.text("Active group: default")

    imgui.spacing()

    state_names = app._state_machine.state_names
    group_names = list(app._state_groups.keys())
    event_types = ["note_on", "note_off", "cc", "program_change"]
    event_labels = ["Note On", "Note Off", "CC", "Program Change"]
    actions = ["set_group", "set_state", "toggle_mic"]
    action_labels = ["Set Group", "Set State", "Toggle Mic"]

    # Mapping table
    remove_idx = -1
    any_changed = False
    for i, mc in enumerate(config.midi_mappings):
        imgui.push_id(f"midi_{i}")

        # Event type
        et_idx = event_types.index(mc.event_type) if mc.event_type in event_types else 0
        changed, new_idx = imgui.combo("Event", et_idx, event_labels)
        if changed:
            mc.event_type = event_types[new_idx]
            any_changed = True

        # Channel
        changed, new_ch = imgui.slider_int("Channel", mc.channel, 0, 15)
        if changed:
            mc.channel = new_ch
            any_changed = True

        # Note/CC number
        changed, new_note = imgui.input_int("Note/CC", mc.note, 1, 12)
        if changed:
            mc.note = max(0, min(127, new_note))
            any_changed = True

        # Action
        act_idx = actions.index(mc.action) if mc.action in actions else 0
        changed, new_idx = imgui.combo("Action", act_idx, action_labels)
        if changed:
            mc.action = actions[new_idx]
            any_changed = True

        # Target (depends on action)
        if mc.action == "set_group":
            target_names = ["(default)"] + group_names
            t_idx = target_names.index(mc.target) if mc.target in target_names else 0
            changed, new_idx = imgui.combo("Target Group", t_idx, target_names)
            if changed:
                mc.target = target_names[new_idx] if new_idx > 0 else ""
                any_changed = True
            if not group_names:
                imgui.text_colored(imgui.ImVec4(1.0, 0.8, 0.3, 1.0),
                                   "Define groups in the Mic tab first")

            # Mode: momentary vs toggle
            modes = ["momentary", "toggle"]
            mode_labels = ["Momentary (while held)", "Toggle (stays active)"]
            mode_idx = modes.index(mc.mode) if mc.mode in modes else 0
            changed, new_idx = imgui.combo("Mode", mode_idx, mode_labels)
            if changed:
                mc.mode = modes[new_idx]
                any_changed = True
        elif mc.action == "set_state":
            target_names = ["(none)"] + state_names
            t_idx = target_names.index(mc.target) if mc.target in target_names else 0
            changed, new_idx = imgui.combo("Target State", t_idx, target_names)
            if changed:
                mc.target = target_names[new_idx] if new_idx > 0 else ""
                any_changed = True

        # Device filter
        changed, new_dev = imgui.input_text("Device", mc.device)
        if changed:
            mc.device = new_dev
            any_changed = True

        # Learn button for this mapping
        if not midi.learn_mode:
            if imgui.button("Learn"):
                _learn_target_idx = i
                _learn_status = ""
                _learn_config = config
                midi.start_learn(_on_midi_learn)

        imgui.same_line()
        if imgui.button("Remove"):
            remove_idx = i

        imgui.separator()
        imgui.pop_id()

    if remove_idx >= 0:
        config.midi_mappings.pop(remove_idx)
        any_changed = True

    imgui.spacing()
    if imgui.button("+ Add Mapping"):
        from nixchirp.config import MidiMappingConfig
        config.midi_mappings.append(MidiMappingConfig())
        any_changed = True

    if any_changed:
        _sync_mappings_to_midi(app)


def _sync_mappings_to_midi(app: App) -> None:
    """Sync config MIDI mappings to the MidiInput's runtime mapping list."""
    if not app._midi:
        return
    from nixchirp.input.midi import MidiMapping
    app._midi.mappings = [
        MidiMapping(
            device=m.device,
            event_type=m.event_type,
            channel=m.channel,
            note=m.note,
            action=m.action,
            target=m.target,
            mode=m.mode,
        )
        for m in app.config.midi_mappings
    ]
