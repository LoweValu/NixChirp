"""General settings and profile management GUI panel."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from imgui_bundle import imgui

from nixchirp.config import get_profiles_dir, list_profiles

if TYPE_CHECKING:
    from nixchirp.app import App

logger = logging.getLogger(__name__)

# Mutable state for the "Save As" text input
_save_as_path: str = ""
_status_message: str = ""
_status_timer: float = 0.0


def draw_general_panel(app: App) -> None:
    """Draw the general settings and profile management panel."""
    global _save_as_path, _status_message, _status_timer
    config = app.config

    # Profile name
    changed, new_name = imgui.input_text("Profile Name", config.general.profile_name)
    if changed:
        config.general.profile_name = new_name

    imgui.spacing()
    imgui.separator()
    imgui.text("Sleep Timer")
    imgui.spacing()

    # Sleep timeout
    changed, val = imgui.slider_int("Sleep timeout (s)", config.general.sleep_timeout_seconds, 0, 300)
    if changed:
        config.general.sleep_timeout_seconds = val
        if app._sleep_timer:
            app._sleep_timer.timeout = float(val)
    if config.general.sleep_timeout_seconds == 0:
        imgui.text_colored(imgui.ImVec4(0.6, 0.6, 0.6, 1.0), "Sleep disabled")

    # Sleep state
    state_names = app._state_machine.state_names
    target_names = ["(disabled)"] + state_names
    current = config.general.sleep_state
    t_idx = target_names.index(current) if current in target_names else 0
    changed, new_idx = imgui.combo("Sleep state", t_idx, target_names)
    if changed:
        config.general.sleep_state = target_names[new_idx] if new_idx > 0 else ""

    imgui.spacing()
    imgui.separator()
    imgui.text("Cache")
    imgui.spacing()

    # Cache size
    cache_mb = int(app.cache.current_mb)
    cache_max = app.cache.max_mb
    imgui.text(f"Frame cache: {cache_mb} / {cache_max} MB ({app.cache.entry_count} animations)")

    imgui.spacing()
    imgui.separator()
    imgui.text("Profile Management")
    imgui.spacing()

    # Save to current path
    if config.config_path:
        imgui.text(f"Loaded from: {config.config_path}")
        if imgui.button("Save"):
            try:
                config.to_toml(config.config_path)
                _status_message = f"Saved to {config.config_path.name}"
                _status_timer = 3.0
                logger.info("Config saved to %s", config.config_path)
            except Exception as e:
                _status_message = f"Save failed: {e}"
                _status_timer = 5.0
                logger.error("Failed to save config: %s", e)
    else:
        imgui.text("No profile file loaded (using defaults)")

    # Save As — default to XDG profiles dir
    imgui.spacing()
    if not _save_as_path:
        _save_as_path = str(get_profiles_dir() / "my_avatar.toml")
    changed, _save_as_path = imgui.input_text("Save path", _save_as_path)
    imgui.same_line()
    if imgui.button("Save As"):
        if _save_as_path.strip():
            try:
                path = Path(_save_as_path.strip())
                if not path.suffix:
                    path = path.with_suffix(".toml")
                path.parent.mkdir(parents=True, exist_ok=True)
                config.to_toml(path)
                config.config_path = path
                _status_message = f"Saved to {path.name}"
                _status_timer = 3.0
                logger.info("Config saved to %s", path)
            except Exception as e:
                _status_message = f"Save failed: {e}"
                _status_timer = 5.0
                logger.error("Failed to save config: %s", e)

    # Show saved profiles
    profiles = list_profiles()
    if profiles:
        imgui.spacing()
        imgui.text("Saved profiles:")
        for p in profiles:
            imgui.bullet_text(f"{p.stem}  ({p})")
        imgui.text_colored(
            imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
            "Launch with: nixchirp --profile <path>",
        )

    # Status message
    if _status_timer > 0:
        imgui.spacing()
        imgui.text_colored(imgui.ImVec4(0.4, 1.0, 0.4, 1.0), _status_message)

    imgui.spacing()
    imgui.separator()

    # About
    if imgui.collapsing_header("About"):
        from nixchirp import __version__
        imgui.text(f"NixChirp v{__version__}")
        imgui.text("Lightweight Linux-first VTuber PNGTubing app")
        imgui.spacing()
        imgui.text("Press F1 to toggle this panel")


def update_general_timer(dt: float) -> None:
    """Update the status message timer."""
    global _status_timer
    if _status_timer > 0:
        _status_timer -= dt
