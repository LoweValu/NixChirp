"""State machine — manages current state, transitions, and event routing."""

from __future__ import annotations

import logging
import queue
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

from nixchirp.state.state import State

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events that can trigger state changes."""

    MIC_ACTIVE = auto()      # Mic detected speech
    MIC_IDLE = auto()        # Mic went silent
    MIC_INTENSE = auto()     # Mic detected loud input
    MIDI_TRIGGER = auto()    # MIDI event (set_state)
    GROUP_CHANGE = auto()    # Switch active state group (set_group)
    HOTKEY_TRIGGER = auto()  # Keyboard hotkey
    IDLE_TIMEOUT = auto()    # Idle timer expired
    IDLE_CANCEL = auto()     # Activity resumed from idle
    SET_STATE = auto()       # Direct state change request


@dataclass
class StateEvent:
    """An event requesting a state change."""

    event_type: EventType
    target_state: str = ""   # State name to transition to (for SET_STATE, MIDI, HOTKEY)
    value: float = 0.0       # Optional value (e.g., mic RMS level, MIDI velocity)


class StateMachine:
    """Manages avatar states and transitions between them.

    Input sources (mic, MIDI, hotkeys, idle timer) push StateEvents
    into the event queue. The main loop calls update() each frame
    to process events and trigger transitions.
    """

    def __init__(self) -> None:
        self._states: dict[str, State] = {}
        self._current_state: State | None = None
        self._previous_state: State | None = None
        self._default_state: str = ""
        self._event_queue: queue.Queue[StateEvent] = queue.Queue()

        # Mic state mapping
        self.mic_idle_state: str = ""
        self.mic_active_state: str = ""
        self.mic_intense_state: str = ""

        # Callbacks for state changes
        self._on_state_change: list[Callable[[State | None, State, str], None]] = []

    def add_state(self, state: State) -> None:
        """Register a state."""
        self._states[state.name] = state
        if self._current_state is None:
            self._current_state = state
            self._default_state = state.name

    def get_state(self, name: str) -> State | None:
        """Look up a state by name."""
        return self._states.get(name)

    @property
    def current_state(self) -> State | None:
        return self._current_state

    @property
    def previous_state(self) -> State | None:
        return self._previous_state

    @property
    def state_names(self) -> list[str]:
        return list(self._states.keys())

    def set_default_state(self, name: str) -> None:
        """Set which state is the default/fallback."""
        if name in self._states:
            self._default_state = name

    def push_event(self, event: StateEvent) -> None:
        """Push an event to be processed on the next update()."""
        self._event_queue.put_nowait(event)

    def on_state_change(self, callback: Callable[[State | None, State, str], None]) -> None:
        """Register a callback for state changes.

        Callback receives (old_state, new_state, transition_type).
        """
        self._on_state_change.append(callback)

    def update(self) -> StateEvent | None:
        """Process pending events. Returns the event that caused a state change, or None."""
        last_event = None
        while not self._event_queue.empty():
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                break
            result = self._handle_event(event)
            if result:
                last_event = event
        return last_event

    def _handle_event(self, event: StateEvent) -> bool:
        """Handle a single event. Returns True if state changed."""
        target_name = self._resolve_target(event)
        if not target_name or target_name not in self._states:
            return False

        target = self._states[target_name]
        if target is self._current_state:
            return False

        old_state = self._current_state
        self._previous_state = old_state
        self._current_state = target

        # Determine transition type
        transition_type = "cut"
        if old_state and old_state.transition_out != "cut":
            transition_type = old_state.transition_out
        elif target.transition_in != "cut":
            transition_type = target.transition_in

        logger.debug(
            "State: %s → %s (%s)",
            old_state.name if old_state else "None",
            target.name,
            transition_type,
        )

        for cb in self._on_state_change:
            cb(old_state, target, transition_type)

        return True

    def _resolve_target(self, event: StateEvent) -> str:
        """Determine the target state name from an event."""
        if event.event_type == EventType.SET_STATE:
            return event.target_state

        if event.event_type == EventType.MIC_ACTIVE:
            return self.mic_active_state

        if event.event_type == EventType.MIC_IDLE:
            return self.mic_idle_state

        if event.event_type == EventType.MIC_INTENSE:
            return self.mic_intense_state or self.mic_active_state

        if event.event_type in (EventType.MIDI_TRIGGER, EventType.HOTKEY_TRIGGER):
            return event.target_state

        if event.event_type == EventType.IDLE_TIMEOUT:
            return event.target_state or self._default_state

        if event.event_type == EventType.IDLE_CANCEL:
            return self.mic_idle_state or self._default_state

        return ""
