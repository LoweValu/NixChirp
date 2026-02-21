"""Main application loop — SDL2 event loop with animation rendering."""

from __future__ import annotations

import argparse
import ctypes
import logging
import queue
import time
from pathlib import Path

import sdl2

from nixchirp.assets.cache import FrameCache
from nixchirp.assets.loader import LoadedAnimation
from nixchirp.config import AppConfig, StateConfig, load_profile
from nixchirp.constants import (
    CHROMA_GREEN,
    DEFAULT_BG_COLOR,
    DEFAULT_FPS_CAP,
    DEFAULT_WINDOW_TITLE,
    OUTPUT_CHROMA,
    OUTPUT_TRANSPARENT,
    OUTPUT_VIRTUAL_CAM,
)
from nixchirp.gui.imgui_sdl2 import ImGuiSDL2
from nixchirp.gui.overlay import draw_overlay
from nixchirp.input.hotkeys import HotkeyInput, HotkeyMapping
from nixchirp.input.idle import SleepEvent, SleepTimer
from nixchirp.input.mic import MicInput
from nixchirp.input.midi import MidiInput, MidiMapping
from nixchirp.render.gl_renderer import GLRenderer
from nixchirp.render.virtual_cam import VirtualCamera
from nixchirp.render.window import Window
from nixchirp.state.machine import EventType, StateEvent, StateMachine
from nixchirp.state.state import State
from nixchirp.state.transitions import Transition, TransitionType, parse_transition_type

logger = logging.getLogger(__name__)


class App:
    """NixChirp main application."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.window: Window | None = None
        self.renderer: GLRenderer | None = None
        self.cache = FrameCache(max_mb=config.general.cache_max_mb)

        # State machine
        self._state_machine = StateMachine()
        self._event_queue: queue.Queue[StateEvent] = queue.Queue()

        # Input
        self._mic: MicInput | None = None
        self._midi: MidiInput | None = None
        self._hotkeys: HotkeyInput | None = None
        self._sleep_timer: SleepTimer | None = None

        # Virtual camera output
        self._virtual_cam: VirtualCamera | None = None

        # GUI
        self._imgui = ImGuiSDL2()
        self._gui_visible = False

        # Animation playback — current state
        self._current_animation: LoadedAnimation | None = None
        self._current_frame_index: int = 0
        self._frame_timer: float = 0.0
        self._speed_multiplier: float = 1.0
        self._loop: bool = True

        # Animation position memory: state_name → (frame_index, frame_timer)
        # Allows resuming looping animations where they left off instead of
        # restarting from frame 0 on every mic idle↔speaking cycle.
        self._anim_positions: dict[str, tuple[int, float]] = {}

        # Flag: True when processing mic-driven state changes.
        # Mic transitions use instant swap keeping the current frame position
        # so idle/speaking animations stay in sync (same body, different mouth).
        self._mic_transition: bool = False

        # Animation playback — previous state (for crossfade)
        self._prev_animation: LoadedAnimation | None = None
        self._prev_frame_index: int = 0
        self._prev_frame_timer: float = 0.0
        self._prev_speed: float = 1.0

        # Transition
        self._transition: Transition | None = None
        self._default_transition_type = parse_transition_type(config.transitions.default_type)
        self._default_transition_duration = config.transitions.default_duration_ms

        # Timing
        self._last_time: float = 0.0
        self._fps_cap = config.general.fps_cap or DEFAULT_FPS_CAP
        self._frame_time_target = 1.0 / self._fps_cap

        # State groups: group_name → (idle_state, active_state, intense_state)
        self._state_groups: dict[str, tuple[str, str, str]] = {}
        self._active_group: str = ""  # "" means default (from mic config)
        self._group_revert_pending: bool = False
        self._group_revert_timer: float = 0.0
        self._group_activate_time: float = 0.0  # monotonic time when group was activated
        self._group_mic_lock_until: float = 0.0  # suppress mic transitions until this time

        # Volume meter for debug logging
        self._volume_log_timer: float = 0.0

    def run(self) -> None:
        """Run the main application loop."""
        try:
            self._init()
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self._cleanup()

    def _init(self) -> None:
        """Initialize window, renderer, state machine, GUI, and inputs."""
        res = self.config.output.resolution
        mode = self.config.output.mode

        # Window + GL
        self.window = Window(
            title=DEFAULT_WINDOW_TITLE,
            width=res[0],
            height=res[1],
            output_mode=mode,
        )
        self.window.create()

        self.renderer = GLRenderer()
        self.renderer.init()

        w, h = self.window.get_size()
        self.renderer.set_viewport(w, h)

        # Initialize ImGui (must be after GL context)
        self._imgui.init()

        # Build states from config
        for sc in self.config.states:
            state = State(
                name=sc.name,
                file=sc.file,
                loop=sc.loop,
                speed=sc.speed,
                group=sc.group,
            )
            self._state_machine.add_state(state)

        # Configure mic→state mapping
        self._state_machine.mic_idle_state = self.config.mic.idle_state
        self._state_machine.mic_active_state = self.config.mic.active_state
        self._state_machine.mic_intense_state = self.config.mic.intense_state

        # Register state change callback
        self._state_machine.on_state_change(self._on_state_change)

        # Preload all configured states into cache
        self._preload_states()

        # Set initial state's animation
        current = self._state_machine.current_state
        if current:
            self._load_state_animation(current)

        # Start mic input
        mic_cfg = self.config.mic
        self._mic = MicInput(
            event_queue=self._event_queue,
            device=mic_cfg.device,
            open_threshold=mic_cfg.open_threshold,
            close_threshold=mic_cfg.close_threshold,
            intense_threshold=mic_cfg.intense_threshold,
            hold_time_ms=mic_cfg.hold_time_ms,
        )
        if self._mic.available and self._state_machine.mic_active_state:
            self._mic.start()
            logger.info("Mic input enabled (open=%.2f, close=%.2f, hold=%dms)",
                        mic_cfg.open_threshold, mic_cfg.close_threshold, mic_cfg.hold_time_ms)
        else:
            if not self._state_machine.mic_active_state:
                logger.info("Mic input disabled — no mic states configured")
            else:
                logger.info("Mic input unavailable")

        # Build state groups from config
        for sg in self.config.state_groups:
            if sg.name:
                self._state_groups[sg.name] = (sg.idle_state, sg.active_state, sg.intense_state)
                logger.info("State group '%s': idle=%s, active=%s, intense=%s",
                            sg.name, sg.idle_state, sg.active_state, sg.intense_state)

        # Start MIDI input
        midi_mappings = [
            MidiMapping(
                device=m.device,
                event_type=m.event_type,
                channel=m.channel,
                note=m.note,
                action=m.action,
                target=m.target,
                mode=m.mode,
            )
            for m in self.config.midi_mappings
        ]
        self._midi = MidiInput(
            event_queue=self._event_queue,
            mappings=midi_mappings,
        )
        if self._midi.available:
            self._midi.start()
            logger.info("MIDI input enabled (%d mappings)", len(midi_mappings))
        else:
            logger.info("MIDI input unavailable — install alsa-midi for MIDI support")

        # Start global hotkey input (XDG Desktop Portal)
        hotkey_mappings = [
            HotkeyMapping(action=h.action, target=h.target)
            for h in self.config.hotkeys
        ]
        self._hotkeys = HotkeyInput(
            event_queue=self._event_queue,
            mappings=hotkey_mappings,
        )
        if self._hotkeys.available:
            self._hotkeys.start()
            logger.info("Hotkey portal starting (%d mappings)", len(hotkey_mappings))
        else:
            logger.info("Global hotkeys unavailable — install dbus-fast")

        # Sleep timer
        self._sleep_timer = SleepTimer(
            timeout_seconds=float(self.config.general.sleep_timeout_seconds),
        )
        if self.config.general.sleep_state:
            logger.info("Sleep timer enabled: %ds → state '%s'",
                        self.config.general.sleep_timeout_seconds,
                        self.config.general.sleep_state)
        else:
            logger.info("Sleep timer: no sleep state configured (disabled)")

        # Virtual camera output (opened at startup if mode is virtual_cam;
        # can also be opened/closed at runtime from the GUI)
        if mode == OUTPUT_VIRTUAL_CAM:
            self.open_virtual_cam()

        self._last_time = time.monotonic()

        # First-run: auto-show GUI if no states configured
        if not self.config.states:
            self._gui_visible = True
            logger.info("No states configured — opening settings panel")

        logger.info("NixChirp initialized (%s mode, %dx%d). Press F1 for settings.", mode, res[0], res[1])

    def _resolve_asset_path(self, file_path: str) -> Path | None:
        """Resolve an asset path relative to the config file or as absolute."""
        p = Path(file_path)
        if p.is_absolute():
            return p

        if self.config.config_path:
            candidate = self.config.config_path.parent / p
            if candidate.exists():
                return candidate

        candidate = Path.cwd() / p
        if candidate.exists():
            return candidate

        return p

    def _preload_states(self) -> None:
        """Preload all configured state animations into cache at startup."""
        paths_to_load: list[tuple[str, Path]] = []
        for state_name in self._state_machine.state_names:
            state = self._state_machine.get_state(state_name)
            if state is None:
                continue
            file_path = self._resolve_asset_path(state.file)
            if file_path and file_path.exists():
                paths_to_load.append((state_name, file_path))
            else:
                logger.warning("Asset not found for state '%s': %s", state_name, state.file)

        if not paths_to_load:
            return

        original_max = self.cache._max_bytes
        self.cache._max_bytes = 2**63

        logger.info("Preloading %d state animations...", len(paths_to_load))
        for state_name, file_path in paths_to_load:
            self.cache.get_or_load(file_path)

        loaded_mb = int(self.cache.current_mb)
        new_max = max(original_max // (1024 * 1024), loaded_mb + 100)
        self.cache._max_bytes = new_max * 1024 * 1024
        logger.info("Preloaded %d states (%.0f MB). Cache limit: %d MB",
                     len(paths_to_load), self.cache.current_mb, new_max)

    def _load_state_animation(self, state: State) -> LoadedAnimation | None:
        """Load an animation for a state, using the cache."""
        file_path = self._resolve_asset_path(state.file)
        if file_path is None or not file_path.exists():
            logger.warning("Asset not found for state '%s': %s", state.name, state.file)
            return None

        anim = self.cache.get_or_load(file_path)
        self._current_animation = anim
        self._speed_multiplier = state.speed
        self._loop = state.loop

        # For looping animations, resume from the saved position so that
        # rapid mic idle↔speaking cycling doesn't visually restart the GIF.
        saved = self._anim_positions.get(state.name)
        if saved and state.loop and anim.frame_count > 0:
            self._current_frame_index = saved[0] % anim.frame_count
            self._frame_timer = saved[1]
        else:
            self._current_frame_index = 0
            self._frame_timer = 0.0

        return anim

    def _on_state_change(self, old_state: State | None, new_state: State, transition_type_str: str) -> None:
        """Callback when the state machine changes state."""
        if self._mic_transition:
            # Mic-driven transition: instant swap keeping the current frame
            # position.  Since idle/speaking GIFs are the same body animation
            # (same length & FPS), keeping the frame index means the body
            # stays perfectly in sync — only the mouth changes.
            file_path = self._resolve_asset_path(new_state.file)
            if file_path and file_path.exists():
                anim = self.cache.get_or_load(file_path)
                self._current_animation = anim
                self._speed_multiplier = new_state.speed
                self._loop = new_state.loop
                # Clamp frame index for safety (different-length animations)
                if anim.frame_count > 0:
                    self._current_frame_index %= anim.frame_count
            # No transition, no prev_animation setup
            self._transition = None
            self._prev_animation = None
            logger.info("State: %s → %s (mic swap)",
                         old_state.name if old_state else "None",
                         new_state.name)
            return

        if old_state and self._current_animation:
            # Save playback position so we can resume if we return to this state
            self._anim_positions[old_state.name] = (
                self._current_frame_index, self._frame_timer
            )

            self._prev_animation = self._current_animation
            self._prev_frame_index = self._current_frame_index
            self._prev_frame_timer = self._frame_timer
            self._prev_speed = self._speed_multiplier

            if self.renderer and self._prev_animation.frame_count > 0:
                frame = self._prev_animation.get_frame(self._prev_frame_index)
                self.renderer.upload_frame(frame, slot="b")

        self._load_state_animation(new_state)

        trans_type = self._default_transition_type
        duration = self._default_transition_duration
        self._transition = Transition(trans_type, duration)
        self._transition.start()

        logger.info("State: %s → %s (%s, %dms)",
                     old_state.name if old_state else "None",
                     new_state.name,
                     trans_type.name.lower(),
                     duration)

    def _main_loop(self) -> None:
        """SDL2 event loop with frame timing."""
        assert self.window is not None
        assert self.renderer is not None

        while self.window.running:
            frame_start = time.monotonic()
            dt = frame_start - self._last_time
            self._last_time = frame_start

            # Poll and process SDL events
            self._poll_and_dispatch_events()

            # Process state machine events from inputs
            self._process_events()

            # Tick group revert debounce
            if self._group_revert_pending:
                self._group_revert_timer -= dt
                if self._group_revert_timer <= 0:
                    self._group_revert_pending = False
                    self._set_active_group("")
                    self._group_mic_lock_until = time.monotonic() + 0.15
                    self._state_machine.update()

            # Tick sleep timer
            if self._sleep_timer:
                sleep_event = self._sleep_timer.update(dt)
                if sleep_event == SleepEvent.FELL_ASLEEP:
                    sleep_state = self.config.general.sleep_state
                    if sleep_state:
                        self._state_machine.push_event(
                            StateEvent(EventType.IDLE_TIMEOUT, target_state=sleep_state)
                        )
                        self._state_machine.update()
                        logger.info("Sleep timer: transitioning to '%s'", sleep_state)
                elif sleep_event == SleepEvent.WOKE_UP:
                    # Only push IDLE_CANCEL if we're still in the sleep state.
                    # A mic event in _process_events may have already changed
                    # the state (e.g. to active), so we'd skip the redundant
                    # bounce through idle.
                    current = self._state_machine.current_state
                    sleep_state = self.config.general.sleep_state
                    if current and current.name == sleep_state:
                        self._state_machine.push_event(
                            StateEvent(EventType.IDLE_CANCEL)
                        )
                        self._state_machine.update()
                        logger.info("Sleep timer: waking up → '%s'",
                                    self._state_machine.mic_idle_state)
                    else:
                        logger.info("Sleep timer: woke up (state already changed)")

            # Update animation(s)
            self._update_animation(dt)

            # Update transition
            if self._transition and self._transition.active:
                self._transition.update()

            # Render avatar
            self._render_frame()

            # Write frame to virtual camera (if active)
            if self._virtual_cam and self._virtual_cam.is_open:
                self._write_virtual_cam_frame()

            # Render ImGui overlay
            if self._gui_visible:
                win_w, win_h = ctypes.c_int(), ctypes.c_int()
                sdl2.SDL_GetWindowSize(self.window._window, ctypes.byref(win_w), ctypes.byref(win_h))
                fb_w, fb_h = self.window.get_size()
                self._imgui.new_frame(win_w.value, win_h.value, fb_w, fb_h, dt)
                draw_overlay(self, dt)
                self._imgui.render()

            # Present
            self.window.swap()

            # Debug volume meter
            self._log_volume(dt)

            # Frame rate limiting
            elapsed = time.monotonic() - frame_start
            sleep_time = self._frame_time_target - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _poll_and_dispatch_events(self) -> None:
        """Poll SDL events, feed to ImGui, handle F1 toggle and quit."""
        assert self.window is not None
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == sdl2.SDL_QUIT:
                self.window._running = False
                continue

            # F1 toggles GUI overlay
            if (event.type == sdl2.SDL_KEYDOWN
                    and event.key.keysym.scancode == sdl2.SDL_SCANCODE_F1
                    and event.key.repeat == 0):
                self._gui_visible = not self._gui_visible
                logger.info("GUI overlay %s", "shown" if self._gui_visible else "hidden")
                continue

            # Feed to ImGui if visible
            if self._gui_visible:
                consumed = self._imgui.process_event(event)
                if consumed:
                    continue  # ImGui consumed this event, don't pass to app

    def _process_events(self) -> None:
        """Drain the event queue into the state machine.

        Coalesces mic events — only the latest mic event per frame matters.
        """
        _MIC_EVENTS = {EventType.MIC_ACTIVE, EventType.MIC_IDLE, EventType.MIC_INTENSE}
        latest_mic_event: StateEvent | None = None
        other_events: list[StateEvent] = []

        while not self._event_queue.empty():
            try:
                event = self._event_queue.get_nowait()
                if event.event_type in _MIC_EVENTS:
                    latest_mic_event = event
                else:
                    other_events.append(event)
            except queue.Empty:
                break

        group_activated = False
        for event in other_events:
            # Handle MIDI toggle_mic special action
            if (event.event_type == EventType.MIDI_TRIGGER
                    and event.target_state == "__toggle_mic__"):
                self._toggle_mic()
                continue
            # Handle state group changes
            if event.event_type == EventType.GROUP_CHANGE:
                target = event.target_state
                if not target or target == "default":
                    # Momentary release — delay revert by remaining minimum
                    # hold time so quick taps still show the group cleanly,
                    # and sustained holds release immediately.
                    _MIN_HOLD_S = 0.30  # group stays active for at least 300ms
                    _DEBOUNCE_S = 0.05  # minimum delay to absorb spurious OFF/ON
                    held = time.monotonic() - self._group_activate_time
                    remaining = max(_MIN_HOLD_S - held, _DEBOUNCE_S)
                    self._group_revert_pending = True
                    self._group_revert_timer = remaining
                else:
                    # Activating a group — role-based transition determines
                    # correct initial state from current state machine state
                    self._group_revert_pending = False
                    self._set_active_group(target)
                    self._group_activate_time = time.monotonic()
                    self._group_mic_lock_until = time.monotonic() + 0.15
                    group_activated = True
                continue
            self._state_machine.push_event(event)

        # Process non-mic events (group changes, MIDI triggers, etc.)
        # with normal transition behavior.
        self._state_machine.update()

        # Process mic event separately with instant-swap behavior so
        # idle↔speaking transitions are seamless (no transition effect,
        # frame position preserved for body sync).
        mic_locked = time.monotonic() < self._group_mic_lock_until
        if latest_mic_event is not None and not group_activated and not mic_locked:
            self._mic_transition = True
            self._state_machine.push_event(latest_mic_event)
            self._state_machine.update()
            self._mic_transition = False

        # Feed activity signals to the sleep timer.
        # Any non-idle mic event, MIDI event, or hotkey event counts as activity.
        if self._sleep_timer:
            _ACTIVE_MIC = {EventType.MIC_ACTIVE, EventType.MIC_INTENSE}
            has_activity = (
                (latest_mic_event is not None and latest_mic_event.event_type in _ACTIVE_MIC)
                or other_events  # Any MIDI/hotkey/group event
            )
            if has_activity:
                self._sleep_timer.activity()

    def _update_animation(self, dt: float) -> None:
        """Advance the current (and previous, during crossfade) animation."""
        anim = self._current_animation
        if anim is not None and anim.frame_count > 0:
            self._frame_timer += dt * 1000.0 * self._speed_multiplier
            frame_dur = anim.frame_duration_ms or 33.33
            while self._frame_timer >= frame_dur:
                self._frame_timer -= frame_dur
                self._current_frame_index += 1
                if self._current_frame_index >= anim.frame_count:
                    if self._loop:
                        self._current_frame_index = 0
                    else:
                        self._current_frame_index = anim.frame_count - 1
                        self._frame_timer = 0.0
                        break

        if self._transition and self._transition.active and self._prev_animation:
            prev = self._prev_animation
            if prev.frame_count > 0:
                self._prev_frame_timer += dt * 1000.0 * self._prev_speed
                frame_dur = prev.frame_duration_ms or 33.33
                while self._prev_frame_timer >= frame_dur:
                    self._prev_frame_timer -= frame_dur
                    self._prev_frame_index += 1
                    if self._prev_frame_index >= prev.frame_count:
                        self._prev_frame_index = 0

    def _render_frame(self) -> None:
        """Render the current frame to the screen."""
        assert self.renderer is not None
        assert self.window is not None

        mode = self.config.output.mode
        if mode == OUTPUT_CHROMA:
            bg = CHROMA_GREEN
        elif mode == OUTPUT_TRANSPARENT:
            bg = DEFAULT_BG_COLOR
        else:
            bg = (0.15, 0.15, 0.15, 1.0)

        w, h = self.window.get_size()
        self.renderer.set_viewport(w, h)
        self.renderer.clear(bg)

        anim = self._current_animation
        if anim is None or anim.frame_count == 0:
            return

        frame = anim.get_frame(self._current_frame_index)
        self.renderer.upload_frame(frame, slot="a")

        if (self._transition and self._transition.active
                and self._prev_animation and self._prev_animation.frame_count > 0):
            prev_frame = self._prev_animation.get_frame(self._prev_frame_index)
            self.renderer.upload_frame(prev_frame, slot="b")
            blend = self._transition.blend
            self.renderer.render_crossfade(1.0 - blend, bg)
        else:
            if mode == OUTPUT_CHROMA:
                self.renderer.render_chroma(CHROMA_GREEN[:3])
            else:
                self.renderer.render_passthrough(bg)

            if self._transition and not self._transition.active:
                self._prev_animation = None
                self._transition = None

    def _write_virtual_cam_frame(self) -> None:
        """Write the current animation frame to the virtual camera."""
        assert self._virtual_cam is not None

        anim = self._current_animation
        if anim is None or anim.frame_count == 0:
            return

        frame = anim.get_frame(self._current_frame_index)

        # Use chroma color as background for virtual camera output
        chroma_hex = self.config.output.chroma_color.lstrip("#")
        try:
            r = int(chroma_hex[0:2], 16)
            g = int(chroma_hex[2:4], 16)
            b = int(chroma_hex[4:6], 16)
        except (ValueError, IndexError):
            r, g, b = 0, 255, 0  # Default green

        self._virtual_cam.write_frame(frame, bg_color=(r, g, b))

    def open_virtual_cam(self) -> bool:
        """Open the virtual camera (called from GUI on mode switch)."""
        if self._virtual_cam and self._virtual_cam.is_open:
            return True
        res = self.config.output.resolution
        self._virtual_cam = VirtualCamera(
            device=self.config.output.virtual_cam_device,
            width=res[0],
            height=res[1],
        )
        ok = self._virtual_cam.open()
        if ok:
            logger.info("Virtual camera started: %s", self.config.output.virtual_cam_device)
        return ok

    def close_virtual_cam(self) -> None:
        """Close the virtual camera (called from GUI on mode switch)."""
        if self._virtual_cam:
            self._virtual_cam.close()
            self._virtual_cam = None
            logger.info("Virtual camera stopped")

    def _set_active_group(self, group_name: str) -> None:
        """Switch the active state group, updating mic state mapping.

        An empty group_name or "default" reverts to the default mic config.

        Uses the current state machine state to determine the correct
        initial state in the new group — if we're currently in an "active"
        state we go to the new group's active state, etc.  This is
        deterministic and avoids race conditions with the audio thread.
        """
        if group_name == self._active_group:
            return  # Already active

        sm = self._state_machine

        # Determine the current state's "role" BEFORE changing mappings.
        # This tells us whether the user is currently idle/speaking/intense
        # from the state machine's perspective (what's on screen).
        current = sm.current_state
        current_role = "idle"
        if current:
            if current.name == sm.mic_active_state:
                current_role = "active"
            elif current.name == sm.mic_intense_state:
                current_role = "intense"

        if not group_name or group_name == "default":
            # Revert to default from mic config
            sm.mic_idle_state = self.config.mic.idle_state
            sm.mic_active_state = self.config.mic.active_state
            sm.mic_intense_state = self.config.mic.intense_state
            self._active_group = ""
            logger.info("State group → default (idle=%s, active=%s, intense=%s)",
                        sm.mic_idle_state, sm.mic_active_state, sm.mic_intense_state)
        elif group_name in self._state_groups:
            idle, active, intense = self._state_groups[group_name]
            sm.mic_idle_state = idle
            sm.mic_active_state = active
            sm.mic_intense_state = intense
            self._active_group = group_name
            logger.info("State group → '%s' (idle=%s, active=%s, intense=%s)",
                        group_name, idle, active, intense)
        else:
            logger.warning("Unknown state group: '%s'", group_name)
            return

        # Map the old role to the new group's equivalent state.
        if current_role == "intense" and sm.mic_intense_state:
            target = sm.mic_intense_state
        elif current_role == "active" and sm.mic_active_state:
            target = sm.mic_active_state
        else:
            target = sm.mic_idle_state

        logger.info("Group switch: role=%s → target=%s", current_role, target)
        if target:
            sm.push_event(StateEvent(EventType.SET_STATE, target_state=target))

    def _toggle_mic(self) -> None:
        """Toggle microphone input on/off (triggered by MIDI)."""
        if not self._mic:
            return
        if self._mic.running:
            self._mic.stop()
            logger.info("Mic toggled OFF via MIDI")
        else:
            self._mic.start()
            logger.info("Mic toggled ON via MIDI")

    def _log_volume(self, dt: float) -> None:
        """Periodically log mic volume for debugging."""
        if not self._mic or not self._mic.available:
            return
        self._volume_log_timer += dt
        if self._volume_log_timer >= 0.5:
            self._volume_log_timer = 0.0
            rms = self._mic.current_rms
            bar_len = int(rms * 50)
            bar = "#" * bar_len + "-" * (50 - bar_len)
            state_name = self._state_machine.current_state.name if self._state_machine.current_state else "?"
            logger.debug("Vol [%s] %.3f | State: %s", bar, rms, state_name)

    def _cleanup(self) -> None:
        """Clean up all resources."""
        if self._virtual_cam:
            self._virtual_cam.close()
        if self._hotkeys:
            self._hotkeys.stop()
        if self._midi:
            self._midi.stop()
        if self._mic:
            self._mic.stop()
        self._imgui.shutdown()
        if self.renderer:
            self.renderer.destroy()
        if self.window:
            self.window.destroy()
        self.cache.clear()
        logger.info("NixChirp shut down")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    from nixchirp import __version__

    parser = argparse.ArgumentParser(
        prog="nixchirp",
        description="Lightweight Linux-first VTuber PNGTubing app",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--profile", type=str, default=None,
        help="Path to a TOML profile file to load",
    )
    parser.add_argument(
        "--file", type=str, default=None,
        help="Quick-start: path to a single animation file (GIF, APNG, WebM)",
    )
    parser.add_argument(
        "--output-mode",
        choices=["windowed", "chroma", "transparent", "virtual_cam"],
        default=None, help="Output mode override",
    )
    parser.add_argument(
        "--fps", type=int, default=None, help="FPS cap override",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging",
    )
    return parser.parse_args()


def _load_example_profile() -> AppConfig | None:
    """Load the bundled example profile (Alex the Cat).

    Tries two locations:
    1. Flatpak install: /app/share/nixchirp/examples/
    2. Package data: nixchirp/data/examples/ (dev/pip install)
    """
    from importlib import resources

    # Try Flatpak install path first
    flatpak_dir = Path("/app/share/nixchirp/examples")
    if flatpak_dir.exists() and (flatpak_dir / "alex_profile.toml").exists():
        profile_path = flatpak_dir / "alex_profile.toml"
        config = load_profile(profile_path)
        # Resolve GIF paths relative to profile location
        for state in config.states:
            if not Path(state.file).is_absolute():
                state.file = str(flatpak_dir / state.file)
        logger.info("Loaded bundled example profile: Alex the Cat (Flatpak)")
        return config

    # Try package data (editable / pip install)
    try:
        examples_dir = resources.files("nixchirp.data.examples")
        profile_file = examples_dir.joinpath("alex_profile.toml")
        # importlib.resources may return a traversable; get real path
        profile_path = Path(str(profile_file))
        if profile_path.exists():
            config = load_profile(profile_path)
            examples_real = profile_path.parent
            for state in config.states:
                if not Path(state.file).is_absolute():
                    state.file = str(examples_real / state.file)
            logger.info("Loaded bundled example profile: Alex the Cat")
            return config
    except Exception:
        pass

    return None


def main() -> None:
    """Application entry point."""
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.profile:
        config = load_profile(Path(args.profile))
    elif args.file:
        config = AppConfig()
        config.states.append(StateConfig(name="default", file=args.file))
    else:
        # Check for saved profiles in XDG config dir
        from nixchirp.config import list_profiles
        profiles = list_profiles()
        if profiles:
            # Load the most recently modified profile
            latest = max(profiles, key=lambda p: p.stat().st_mtime)
            logger.info("No --profile given, loading most recent: %s", latest)
            config = load_profile(latest)
        else:
            # Load bundled example profile (Alex the Cat)
            config = _load_example_profile()
            if config is None:
                config = AppConfig()

    if args.output_mode:
        config.output.mode = args.output_mode
    if args.fps:
        config.general.fps_cap = args.fps

    app = App(config)
    app.run()
