# Phase 5: Global Hotkeys + Sleep Timer — Design

## Summary

Add global keyboard hotkeys (via `evdev`) that work on both X11 and Wayland,
and a sleep timer that transitions the avatar to a designated sleep state after
a configurable period of inactivity.

---

## Global Hotkeys

### Library: `evdev`

- Reads keyboard events directly from `/dev/input/event*` devices
- Works on X11 and Wayland (no display server dependency)
- Compatible with future Flatpak packaging (can request device access)
- Requires user be in the `input` group (`sudo usermod -aG input $USER`)
- Graceful degradation if unavailable (same pattern as `alsa-midi` for MIDI)

### Module: `input/hotkeys.py`

**Class: `HotkeyInput`**

- `__init__(event_queue, mappings)` — same shared queue pattern as MicInput/MidiInput
- `start()` — enumerate keyboard devices, start background poll thread
- `stop()` — stop thread, close devices
- `start_learn(callback)` / `cancel_learn()` — learn mode (same as MIDI)

**Background thread:**
1. Enumerate `/dev/input/event*` devices, filter for keyboards (EV_KEY capability)
2. Use `select()` to poll all keyboard devices simultaneously
3. Track modifier state (Ctrl, Shift, Alt, Super) from key press/release events
4. On non-modifier key press: form combo string (e.g., `ctrl+shift+1`)
5. Match against mappings, push StateEvent to queue

**Data structures:**
```python
@dataclass
class HotkeyMapping:
    keys: str = ""           # e.g., "ctrl+shift+1"
    action: str = "set_group"  # set_group, set_state
    target: str = ""         # group or state name
```

### Supported actions

- `set_group` — switch active state group (same as MIDI set_group, toggle mode)
- `set_state` — jump to a specific state directly

### Config: `HotkeyConfig`

```python
@dataclass
class HotkeyConfig:
    keys: str = ""
    action: str = "set_group"
    target: str = ""
```

Added to `AppConfig.hotkeys: list[HotkeyConfig]`.

### TOML format

```toml
[[hotkeys]]
keys = "ctrl+shift+1"
action = "set_group"
target = "excited"
```

### GUI: `gui/hotkeys_panel.py`

- Mapping table: key combo display, action dropdown (set_group/set_state),
  target selector (group names or state names depending on action)
- "Record" button per mapping — captures next key combo (like MIDI learn)
- "+ Add Hotkey" button
- Remove button per mapping
- Status: shows connected keyboard devices and whether evdev is available
- New "Hotkeys" tab in overlay.py

---

## Sleep Timer

### Naming

Called "sleep" (not "idle") to avoid confusion with mic idle states that users
configure for their normal state groups.

### Module: `input/idle.py`

**Class: `SleepTimer`**

- `__init__(timeout_seconds)` — configurable timeout, default 30s
- `activity()` — call on any input activity to reset the timer
- `update(dt) -> SleepTimerEvent | None` — tick the timer, returns event if
  state changed (FELL_ASLEEP or WOKE_UP)
- `sleeping: bool` — current state property

**NOT a background thread** — ticked from the main loop since it just tracks
elapsed time.

**Activity sources** (fed from `app._process_events()`):
- Mic events (MIC_ACTIVE, MIC_INTENSE — NOT MIC_IDLE)
- MIDI events (any mapping match)
- Hotkey events (any mapping match)

### Config additions

```python
@dataclass
class GeneralConfig:
    ...
    sleep_timeout_seconds: int = 30
    sleep_state: str = ""       # state to transition to when asleep
```

### Integration in `app.py`

```
_process_events():
    ...process mic/MIDI/hotkey events...
    if any activity detected:
        sleep_timer.activity()

_main_loop():
    ...
    event = sleep_timer.update(dt)
    if event == FELL_ASLEEP and sleep_state configured:
        push IDLE_TIMEOUT event
    elif event == WOKE_UP:
        push IDLE_CANCEL event → returns to mic idle state
```

### GUI additions

In the General panel:
- Sleep timeout slider (0 = disabled, 10–300 seconds)
- Sleep state dropdown (list of configured states)

---

## Files to create/modify

| File | Action |
|------|--------|
| `input/hotkeys.py` | **New** — evdev global hotkey capture |
| `input/idle.py` | **New** — sleep timer |
| `gui/hotkeys_panel.py` | **New** — hotkeys GUI tab |
| `gui/overlay.py` | Add Hotkeys tab |
| `config.py` | Add `HotkeyConfig`, update `GeneralConfig` (sleep fields) |
| `app.py` | Wire hotkeys + sleep timer, handle events |
| `constants.py` | Update `DEFAULT_IDLE_TIMEOUT_SECONDS` → `DEFAULT_SLEEP_TIMEOUT_SECONDS = 30` |
| `pyproject.toml` | Add `evdev` to optional dependencies |

## Dependencies

- `evdev` — pip install, pure Python, no compilation needed
