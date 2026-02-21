"""MIDI device handling and event routing via ALSA sequencer."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

from nixchirp.state.machine import EventType, StateEvent

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Try to import alsa_midi; gracefully degrade if unavailable
try:
    import alsa_midi
    _HAS_ALSA_MIDI = True
except (ImportError, OSError):
    _HAS_ALSA_MIDI = False
    logger.warning("alsa-midi not available — MIDI input disabled")


class MidiEventType(Enum):
    """Types of MIDI events we handle."""
    NOTE_ON = auto()
    NOTE_OFF = auto()
    CONTROL_CHANGE = auto()
    PROGRAM_CHANGE = auto()


@dataclass
class MidiEvent:
    """A parsed MIDI event."""
    event_type: MidiEventType
    channel: int = 0
    note: int = 0           # Note number or CC number
    velocity: int = 0       # Velocity or CC value
    port_name: str = ""     # Source port name


@dataclass
class MidiMapping:
    """Maps a MIDI event pattern to an action."""
    device: str = ""                # Device/port name ("" = any device)
    event_type: str = "note_on"     # note_on, note_off, cc, program_change
    channel: int = 0                # MIDI channel (0-15)
    note: int = 0                   # Note/CC number
    action: str = "set_state"       # set_state, toggle_mic, set_group
    target: str = ""                # Target state/group name
    mode: str = "momentary"         # "momentary" (revert on release) or "toggle"

    def matches(self, event: MidiEvent) -> bool:
        """Check if this mapping matches a MIDI event."""
        # Device filter (empty = any)
        if self.device and self.device != event.port_name:
            return False

        # Event type
        type_map = {
            "note_on": MidiEventType.NOTE_ON,
            "note_off": MidiEventType.NOTE_OFF,
            "cc": MidiEventType.CONTROL_CHANGE,
            "program_change": MidiEventType.PROGRAM_CHANGE,
        }
        expected_type = type_map.get(self.event_type)
        if expected_type != event.event_type:
            return False

        # Channel
        if self.channel != event.channel:
            return False

        # Note/CC number
        if event.event_type != MidiEventType.PROGRAM_CHANGE:
            if self.note != event.note:
                return False

        return True

    def matches_release(self, event: MidiEvent) -> bool:
        """Check if this event is the note-off release for a momentary mapping."""
        if self.mode != "momentary":
            return False
        if self.device and self.device != event.port_name:
            return False
        if event.event_type != MidiEventType.NOTE_OFF:
            return False
        if self.channel != event.channel:
            return False
        if self.note != event.note:
            return False
        return True


class MidiInput:
    """ALSA MIDI input — listens for events and routes them via mappings.

    Runs a background thread that polls the ALSA sequencer for incoming
    MIDI events and translates them to state machine events via the
    mapping table.
    """

    def __init__(
        self,
        event_queue: queue.Queue[StateEvent],
        mappings: list[MidiMapping] | None = None,
    ) -> None:
        self._event_queue = event_queue
        self._mappings: list[MidiMapping] = mappings or []
        self._client: alsa_midi.SequencerClient | None = None
        self._port: alsa_midi.Port | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._connected_ports: list[str] = []

        # Learn mode
        self._learn_mode = False
        self._learn_callback = None  # Called with MidiEvent when learn captures

    @property
    def available(self) -> bool:
        return _HAS_ALSA_MIDI

    @property
    def mappings(self) -> list[MidiMapping]:
        return self._mappings

    @mappings.setter
    def mappings(self, value: list[MidiMapping]) -> None:
        self._mappings = value

    @property
    def learn_mode(self) -> bool:
        return self._learn_mode

    @property
    def connected_ports(self) -> list[str]:
        return self._connected_ports

    def start(self) -> None:
        """Start the MIDI listener."""
        if not _HAS_ALSA_MIDI:
            logger.warning("Cannot start MIDI — alsa-midi not available")
            return

        try:
            self._client = alsa_midi.SequencerClient("NixChirp")
            self._port = self._client.create_port(
                "input",
                caps=alsa_midi.PortCaps.WRITE | alsa_midi.PortCaps.SUBS_WRITE,
                type=alsa_midi.PortType.MIDI_GENERIC | alsa_midi.PortType.APPLICATION,
            )
            logger.info("ALSA MIDI client created: %s", self._client.client_id)
        except Exception:
            logger.exception("Failed to create ALSA MIDI client")
            return

        # Auto-connect to all available MIDI input ports
        self._connect_all_ports()

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("MIDI listener started")

    def stop(self) -> None:
        """Stop the MIDI listener."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self._port = None
        self._connected_ports.clear()
        logger.info("MIDI listener stopped")

    def _connect_all_ports(self) -> None:
        """Connect to all available hardware/software MIDI output ports."""
        if not self._client or not self._port:
            return

        self._connected_ports.clear()
        try:
            ports = self._client.list_ports(
                output=True,  # We want ports that OUTPUT midi (so we can read from them)
            )
            for port_info in ports:
                # Skip our own port and system ports
                if port_info.client_id == self._client.client_id:
                    continue
                if port_info.client_id in (0, 14):  # System, Timer
                    continue
                try:
                    self._client.subscribe_port(
                        alsa_midi.Address(port_info.client_id, port_info.port_id),
                        self._port,
                    )
                    name = f"{port_info.client_name}:{port_info.name}"
                    self._connected_ports.append(name)
                    logger.info("Connected to MIDI port: %s", name)
                except Exception:
                    logger.debug("Could not connect to port %s:%s",
                                 port_info.client_name, port_info.name)
        except Exception:
            logger.exception("Error enumerating MIDI ports")

    def connect_port(self, client_id: int, port_id: int) -> bool:
        """Manually connect to a specific MIDI port."""
        if not self._client or not self._port:
            return False
        try:
            self._client.subscribe_port(
                alsa_midi.Address(client_id, port_id),
                self._port,
            )
            return True
        except Exception:
            logger.exception("Failed to connect to port %d:%d", client_id, port_id)
            return False

    def start_learn(self, callback) -> None:
        """Enter learn mode — next MIDI event will be captured and passed to callback.

        Args:
            callback: Called with a MidiEvent when the next event is received.
        """
        self._learn_callback = callback
        self._learn_mode = True
        logger.info("MIDI learn mode started")

    def cancel_learn(self) -> None:
        """Cancel learn mode."""
        self._learn_mode = False
        self._learn_callback = None

    def _listen_loop(self) -> None:
        """Background thread: poll ALSA sequencer for events."""
        while self._running:
            try:
                event = self._client.event_input(timeout=0.1)
                if event is None:
                    continue
                midi_event = self._parse_event(event)
                if midi_event is None:
                    continue

                # Learn mode: capture the event
                if self._learn_mode and self._learn_callback:
                    self._learn_mode = False
                    cb = self._learn_callback
                    self._learn_callback = None
                    cb(midi_event)
                    logger.info("MIDI learn captured: %s ch=%d note=%d vel=%d",
                                midi_event.event_type.name, midi_event.channel,
                                midi_event.note, midi_event.velocity)
                    continue

                # Normal mode: check mappings
                self._route_event(midi_event)

            except Exception:
                if self._running:
                    logger.debug("MIDI listen error", exc_info=True)

    def _parse_event(self, event) -> MidiEvent | None:
        """Parse an alsa_midi event into our MidiEvent."""
        if isinstance(event, alsa_midi.NoteOnEvent):
            if event.velocity == 0:
                # Note On with velocity 0 is treated as Note Off
                return MidiEvent(
                    event_type=MidiEventType.NOTE_OFF,
                    channel=event.channel,
                    note=event.note,
                    velocity=0,
                )
            return MidiEvent(
                event_type=MidiEventType.NOTE_ON,
                channel=event.channel,
                note=event.note,
                velocity=event.velocity,
            )
        elif isinstance(event, alsa_midi.NoteOffEvent):
            return MidiEvent(
                event_type=MidiEventType.NOTE_OFF,
                channel=event.channel,
                note=event.note,
                velocity=event.velocity,
            )
        elif isinstance(event, alsa_midi.ControlChangeEvent):
            return MidiEvent(
                event_type=MidiEventType.CONTROL_CHANGE,
                channel=event.channel,
                note=event.param,
                velocity=event.value,
            )
        elif isinstance(event, alsa_midi.ProgramChangeEvent):
            return MidiEvent(
                event_type=MidiEventType.PROGRAM_CHANGE,
                channel=event.channel,
                note=event.value,
                velocity=0,
            )
        return None

    def _route_event(self, event: MidiEvent) -> None:
        """Match a MIDI event against mappings and push state events."""
        for mapping in self._mappings:
            # Check for momentary release (note_off reverts to default group)
            if mapping.matches_release(event) and mapping.action == "set_group":
                self._event_queue.put_nowait(
                    StateEvent(EventType.GROUP_CHANGE, target_state="")
                )
                logger.debug("MIDI → set_group release → default")
                continue

            if mapping.matches(event):
                if mapping.action == "set_group":
                    self._event_queue.put_nowait(
                        StateEvent(
                            EventType.GROUP_CHANGE,
                            target_state=mapping.target,
                            value=event.velocity / 127.0,
                        )
                    )
                    logger.debug("MIDI → set_group '%s' (%s, vel=%d)",
                                 mapping.target, mapping.mode, event.velocity)
                elif mapping.action == "set_state" and mapping.target:
                    self._event_queue.put_nowait(
                        StateEvent(
                            EventType.MIDI_TRIGGER,
                            target_state=mapping.target,
                            value=event.velocity / 127.0,
                        )
                    )
                    logger.debug("MIDI → set_state '%s' (vel=%d)",
                                 mapping.target, event.velocity)
                elif mapping.action == "toggle_mic":
                    self._event_queue.put_nowait(
                        StateEvent(EventType.MIDI_TRIGGER, target_state="__toggle_mic__")
                    )

    @staticmethod
    def list_ports() -> list[dict]:
        """List available MIDI input/output ports."""
        if not _HAS_ALSA_MIDI:
            return []
        try:
            client = alsa_midi.SequencerClient("NixChirp_enum")
            ports = client.list_ports(output=True)
            result = []
            for p in ports:
                if p.client_id in (0, 14):  # Skip system/timer
                    continue
                result.append({
                    "client_id": p.client_id,
                    "port_id": p.port_id,
                    "name": p.name,
                    "client_name": p.client_name,
                })
            client.close()
            return result
        except Exception:
            logger.debug("Failed to enumerate MIDI ports", exc_info=True)
            return []
