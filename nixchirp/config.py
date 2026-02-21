"""TOML configuration loading and saving, profile management."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from nixchirp.constants import (
    DEFAULT_CACHE_MAX_MB,
    DEFAULT_FPS_CAP,
    DEFAULT_MIC_CLOSE_THRESHOLD,
    DEFAULT_MIC_HOLD_TIME_MS,
    DEFAULT_MIC_OPEN_THRESHOLD,
    DEFAULT_SLEEP_TIMEOUT_SECONDS,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    OUTPUT_WINDOWED,
)


@dataclass
class StateConfig:
    """Configuration for a single animation state."""

    name: str
    file: str
    loop: bool = True
    speed: float = 1.0
    group: str = ""


@dataclass
class TransitionConfig:
    """Transition settings."""

    default_type: str = "cut"
    default_duration_ms: int = 80


@dataclass
class OutputConfig:
    """Output/rendering settings."""

    mode: str = OUTPUT_WINDOWED
    chroma_color: str = "#00FF00"
    resolution: tuple[int, int] = (DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    virtual_cam_device: str = "/dev/video10"


@dataclass
class MicConfig:
    """Microphone settings."""

    device: str = "default"
    open_threshold: float = DEFAULT_MIC_OPEN_THRESHOLD
    close_threshold: float = DEFAULT_MIC_CLOSE_THRESHOLD
    hold_time_ms: int = DEFAULT_MIC_HOLD_TIME_MS
    idle_state: str = ""
    active_state: str = ""
    intense_state: str = ""
    intense_threshold: float = 0.4


@dataclass
class MidiMappingConfig:
    """A single MIDI mapping entry."""

    device: str = ""
    event_type: str = "note_on"
    channel: int = 0
    note: int = 0
    action: str = "set_group"
    target: str = ""
    mode: str = "momentary"  # "momentary" (revert on release) or "toggle" (stays active)


@dataclass
class StateGroupConfig:
    """A named group of mic-reactive states (idle/active/intense).

    MIDI 'set_group' action switches the active group, changing which
    states the mic cycles between.
    """

    name: str = ""
    idle_state: str = ""
    active_state: str = ""
    intense_state: str = ""


@dataclass
class HotkeyConfig:
    """A single global hotkey mapping."""

    keys: str = ""          # e.g., "ctrl+shift+1"
    action: str = "set_group"  # set_group, set_state
    target: str = ""        # group or state name


@dataclass
class GeneralConfig:
    """General application settings."""

    profile_name: str = "Default"
    sleep_timeout_seconds: int = DEFAULT_SLEEP_TIMEOUT_SECONDS
    sleep_state: str = ""  # state to transition to when asleep ("" = disabled)
    fps_cap: int = DEFAULT_FPS_CAP
    cache_max_mb: int = DEFAULT_CACHE_MAX_MB


@dataclass
class AppConfig:
    """Top-level application configuration."""

    general: GeneralConfig = field(default_factory=GeneralConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    mic: MicConfig = field(default_factory=MicConfig)
    transitions: TransitionConfig = field(default_factory=TransitionConfig)
    states: list[StateConfig] = field(default_factory=list)
    state_groups: list[StateGroupConfig] = field(default_factory=list)
    midi_mappings: list[MidiMappingConfig] = field(default_factory=list)
    hotkeys: list[HotkeyConfig] = field(default_factory=list)
    config_path: Path | None = None

    @classmethod
    def from_toml(cls, path: Path) -> AppConfig:
        """Load configuration from a TOML file."""
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls._from_dict(data, config_path=path)

    @classmethod
    def _from_dict(cls, data: dict[str, Any], config_path: Path | None = None) -> AppConfig:
        """Build config from a parsed TOML dict."""
        general_data = data.get("general", {})
        general = GeneralConfig(
            profile_name=general_data.get("profile_name", "Default"),
            sleep_timeout_seconds=general_data.get(
                "sleep_timeout_seconds",
                general_data.get("idle_timeout_seconds", DEFAULT_SLEEP_TIMEOUT_SECONDS),
            ),
            sleep_state=general_data.get("sleep_state", ""),
            fps_cap=general_data.get("fps_cap", DEFAULT_FPS_CAP),
            cache_max_mb=general_data.get("cache_max_mb", DEFAULT_CACHE_MAX_MB),
        )

        output_data = data.get("output", {})
        res = output_data.get("resolution", [DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT])
        output = OutputConfig(
            mode=output_data.get("mode", OUTPUT_WINDOWED),
            chroma_color=output_data.get("chroma_color", "#00FF00"),
            resolution=(res[0], res[1]),
            virtual_cam_device=output_data.get("virtual_cam_device", "/dev/video10"),
        )

        mic_data = data.get("mic", {})
        mic = MicConfig(
            device=mic_data.get("device", "default"),
            open_threshold=mic_data.get("open_threshold", DEFAULT_MIC_OPEN_THRESHOLD),
            close_threshold=mic_data.get("close_threshold", DEFAULT_MIC_CLOSE_THRESHOLD),
            hold_time_ms=mic_data.get("hold_time_ms", DEFAULT_MIC_HOLD_TIME_MS),
            idle_state=mic_data.get("idle_state", ""),
            active_state=mic_data.get("active_state", ""),
            intense_state=mic_data.get("intense_state", ""),
            intense_threshold=mic_data.get("intense_threshold", 0.4),
        )

        trans_data = data.get("transitions", {})
        transitions = TransitionConfig(
            default_type=trans_data.get("default_type", "cut"),
            default_duration_ms=trans_data.get("default_duration_ms", 80),
        )

        states = []
        for s in data.get("states", []):
            states.append(StateConfig(
                name=s["name"],
                file=s["file"],
                loop=s.get("loop", True),
                speed=s.get("speed", 1.0),
                group=s.get("group", ""),
            ))

        state_groups = []
        for sg in data.get("state_groups", []):
            state_groups.append(StateGroupConfig(
                name=sg.get("name", ""),
                idle_state=sg.get("idle_state", ""),
                active_state=sg.get("active_state", ""),
                intense_state=sg.get("intense_state", ""),
            ))

        midi_mappings = []
        midi_data = data.get("midi", {})
        for m in midi_data.get("mappings", []):
            midi_mappings.append(MidiMappingConfig(
                device=m.get("device", ""),
                event_type=m.get("event_type", "note_on"),
                channel=m.get("channel", 0),
                note=m.get("note", 0),
                action=m.get("action", "set_state"),
                target=m.get("target", ""),
                mode=m.get("mode", "momentary"),
            ))

        hotkeys = []
        for h in data.get("hotkeys", []):
            hotkeys.append(HotkeyConfig(
                keys=h.get("keys", ""),
                action=h.get("action", "set_group"),
                target=h.get("target", ""),
            ))

        return cls(
            general=general,
            output=output,
            mic=mic,
            transitions=transitions,
            states=states,
            state_groups=state_groups,
            midi_mappings=midi_mappings,
            hotkeys=hotkeys,
            config_path=config_path,
        )

    def to_toml(self, path: Path) -> None:
        """Save configuration to a TOML file."""
        data = self._to_dict()
        with open(path, "wb") as f:
            tomli_w.dump(data, f)

    def _to_dict(self) -> dict[str, Any]:
        """Convert config to a TOML-compatible dict."""
        return {
            "general": {
                "profile_name": self.general.profile_name,
                "sleep_timeout_seconds": self.general.sleep_timeout_seconds,
                "sleep_state": self.general.sleep_state,
                "fps_cap": self.general.fps_cap,
                "cache_max_mb": self.general.cache_max_mb,
            },
            "output": {
                "mode": self.output.mode,
                "chroma_color": self.output.chroma_color,
                "resolution": list(self.output.resolution),
                "virtual_cam_device": self.output.virtual_cam_device,
            },
            "mic": {
                "device": self.mic.device,
                "open_threshold": self.mic.open_threshold,
                "close_threshold": self.mic.close_threshold,
                "hold_time_ms": self.mic.hold_time_ms,
                "idle_state": self.mic.idle_state,
                "active_state": self.mic.active_state,
                "intense_state": self.mic.intense_state,
                "intense_threshold": self.mic.intense_threshold,
            },
            "transitions": {
                "default_type": self.transitions.default_type,
                "default_duration_ms": self.transitions.default_duration_ms,
            },
            "states": [
                {
                    "name": s.name,
                    "file": s.file,
                    "loop": s.loop,
                    "speed": s.speed,
                }
                for s in self.states
            ],
            "state_groups": [
                {
                    "name": sg.name,
                    "idle_state": sg.idle_state,
                    "active_state": sg.active_state,
                    "intense_state": sg.intense_state,
                }
                for sg in self.state_groups
            ],
            "midi": {
                "mappings": [
                    {
                        "device": m.device,
                        "event_type": m.event_type,
                        "channel": m.channel,
                        "note": m.note,
                        "action": m.action,
                        "target": m.target,
                        "mode": m.mode,
                    }
                    for m in self.midi_mappings
                ],
            },
            "hotkeys": [
                {
                    "keys": h.keys,
                    "action": h.action,
                    "target": h.target,
                }
                for h in self.hotkeys
            ],
        }


def get_config_dir() -> Path:
    """Return the XDG config directory for NixChirp.

    Uses $XDG_CONFIG_HOME/nixchirp if set, otherwise ~/.config/nixchirp.
    Creates the directory (and profiles/ subdirectory) if they don't exist.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg) / "nixchirp"
    else:
        base = Path.home() / ".config" / "nixchirp"
    profiles_dir = base / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return base


def get_profiles_dir() -> Path:
    """Return the default profiles directory."""
    return get_config_dir() / "profiles"


def list_profiles() -> list[Path]:
    """List all .toml profile files in the default profiles directory."""
    profiles_dir = get_profiles_dir()
    if not profiles_dir.exists():
        return []
    return sorted(profiles_dir.glob("*.toml"))


def load_profile(path: Path) -> AppConfig:
    """Load a profile from a TOML file."""
    return AppConfig.from_toml(path)


def get_default_config() -> AppConfig:
    """Return a default configuration."""
    return AppConfig()
