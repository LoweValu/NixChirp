"""Global hotkey capture via XDG Desktop Portal GlobalShortcuts.

Uses the org.freedesktop.portal.GlobalShortcuts D-Bus interface for
Wayland-native global shortcuts.  Works inside Flatpak sandboxes and
requires no special permissions or group membership.

Falls back gracefully when the portal is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from nixchirp.state.machine import EventType, StateEvent

logger = logging.getLogger(__name__)

# Try importing dbus-fast; gracefully degrade if unavailable
try:
    from dbus_fast import Message, MessageType, Variant
    from dbus_fast.aio import MessageBus
    _HAS_DBUS = True
except ImportError:
    _HAS_DBUS = False
    logger.info("dbus-fast not available — global hotkeys disabled")


_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_IFACE = "org.freedesktop.portal.GlobalShortcuts"
_REQUEST_IFACE = "org.freedesktop.portal.Request"


@dataclass
class HotkeyMapping:
    """Maps a shortcut to an action."""

    shortcut_id: str = ""     # Portal shortcut ID (auto-generated)
    action: str = "set_group"  # set_group, set_state
    target: str = ""          # group or state name
    trigger: str = ""         # Bound trigger description (read-only, set by portal)


class HotkeyInput:
    """Global hotkey capture via XDG Desktop Portal GlobalShortcuts.

    Runs an asyncio event loop in a background thread to communicate
    with the D-Bus portal.  Pushes state events to the shared queue.
    """

    def __init__(
        self,
        event_queue: queue.Queue[StateEvent] | None,
        mappings: list[HotkeyMapping] | None = None,
    ) -> None:
        self._event_queue = event_queue
        self._mappings: list[HotkeyMapping] = mappings or []

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._bus: MessageBus | None = None  # type: ignore[assignment]
        self._session_path: str = ""
        self._running = False
        self._shutdown_event: asyncio.Event | None = None
        self._portal_available = False
        self._status: str = "Not started"

        # Token counter for unique D-Bus request handles
        self._token_counter = 0

    @property
    def available(self) -> bool:
        return _HAS_DBUS

    @property
    def running(self) -> bool:
        return self._running

    @property
    def portal_available(self) -> bool:
        return self._portal_available

    @property
    def status(self) -> str:
        return self._status

    @property
    def mappings(self) -> list[HotkeyMapping]:
        return self._mappings

    @mappings.setter
    def mappings(self, value: list[HotkeyMapping]) -> None:
        self._mappings = value

    @property
    def session_active(self) -> bool:
        return bool(self._session_path)

    def _next_token(self) -> str:
        """Generate a unique request token."""
        self._token_counter += 1
        return f"nixchirp_{self._token_counter}"

    def start(self) -> None:
        """Start the portal session in a background thread."""
        if not _HAS_DBUS:
            self._status = "dbus-fast not installed"
            return

        self._running = True
        self._loop = asyncio.new_event_loop()
        self._shutdown_event = asyncio.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
        )
        self._thread.start()

    def _run_loop(self) -> None:
        """Background thread: run asyncio event loop."""
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._portal_main())
        except Exception:
            logger.debug("Portal event loop exited", exc_info=True)

    async def _portal_main(self) -> None:
        """Main async coroutine: connect to D-Bus, create session, listen."""
        assert self._shutdown_event is not None

        try:
            self._bus = await MessageBus().connect()
            logger.info("D-Bus session connected")
        except Exception:
            logger.warning("Cannot connect to session D-Bus", exc_info=True)
            self._status = "D-Bus connection failed"
            self._running = False
            return

        # Check if GlobalShortcuts portal is available
        try:
            introspection = await self._bus.introspect(_PORTAL_BUS, _PORTAL_PATH)
            proxy = self._bus.get_proxy_object(_PORTAL_BUS, _PORTAL_PATH, introspection)
            iface = proxy.get_interface(_PORTAL_IFACE)
            self._portal_available = True
            logger.info("GlobalShortcuts portal found")
        except Exception as e:
            logger.info("GlobalShortcuts portal not available: %s", e)
            self._status = "Portal not available"
            self._running = False
            return

        # Create session
        try:
            session_token = self._next_token()
            request_token = self._next_token()

            result = await self._call_with_response(
                iface, "create_session",
                {
                    "handle_token": Variant("s", request_token),
                    "session_handle_token": Variant("s", session_token),
                },
            )
            if result is None:
                self._status = "Session creation failed (no response)"
                logger.warning("Portal CreateSession: no response received")
                self._running = False
                return

            response_code = result[0]
            response_data = result[1]

            if response_code != 0:
                logger.warning("Portal CreateSession denied (code %d)", response_code)
                self._status = "Session denied"
                self._running = False
                return

            self._session_path = response_data.get("session_handle", Variant("s", "")).value
            logger.info("Portal session created: %s", self._session_path)
            self._status = "Connected"

        except Exception:
            logger.warning("Failed to create portal session", exc_info=True)
            self._status = "Session creation error"
            self._running = False
            return

        # Subscribe to Activated/Deactivated signals
        try:
            iface.on_activated(self._on_activated)
            iface.on_deactivated(self._on_deactivated)
            logger.debug("Subscribed to portal Activated/Deactivated signals")
        except Exception:
            logger.warning("Failed to subscribe to portal signals", exc_info=True)

        # If we have mappings, bind them now
        if self._mappings:
            await self._bind_shortcuts_async(iface)

        # Keep the event loop running to receive signals.
        # Wait on shutdown_event so stop() can wake us cleanly.
        await self._shutdown_event.wait()

        # Cleanup
        try:
            self._bus.disconnect()
        except Exception:
            pass
        logger.debug("Portal main loop exited")

    async def _call_with_response(self, iface, method_name: str, *args):
        """Call a portal method and wait for its Response signal.

        Portal methods return a request object path.  The actual result
        arrives as a Response signal on that path.  We use a raw message
        handler (not introspection) because the request object doesn't
        exist until AFTER the method call.
        """
        assert self._bus is not None
        assert self._loop is not None

        response_future: asyncio.Future = self._loop.create_future()

        # Compute the expected request object path.
        sender = self._bus.unique_name.replace(".", "_").lstrip(":")
        token = None
        if args and isinstance(args[0], dict):
            ht = args[0].get("handle_token")
            if ht:
                token = ht.value
        if not token:
            token = self._next_token()
            if args and isinstance(args[0], dict):
                args[0]["handle_token"] = Variant("s", token)

        request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

        # Subscribe via raw message handler BEFORE making the call.
        # This avoids the race: the request object doesn't exist yet,
        # so we can't introspect it.  The handler matches by path.
        def _response_handler(msg: Message) -> bool:
            if (msg.message_type == MessageType.SIGNAL
                    and msg.path == request_path
                    and msg.member == "Response"
                    and msg.interface == _REQUEST_IFACE):
                body = msg.body  # [uint32 response, dict results]
                if len(body) >= 2 and not response_future.done():
                    self._loop.call_soon_threadsafe(
                        response_future.set_result, (body[0], body[1])
                    )
                return True  # Remove handler after first match
            return False

        self._bus.add_message_handler(_response_handler)

        # Make the actual call
        try:
            method = getattr(iface, f"call_{method_name}")
            result = await method(*args)
            logger.debug("Portal %s call returned: %s", method_name, result)
        except Exception:
            logger.warning("Portal %s call failed", method_name, exc_info=True)
            # Remove our handler since we won't get a response
            try:
                self._bus.remove_message_handler(_response_handler)
            except Exception:
                pass
            return None

        # Wait for response with timeout
        try:
            return await asyncio.wait_for(response_future, timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("Portal %s response timed out (30s)", method_name)
            try:
                self._bus.remove_message_handler(_response_handler)
            except Exception:
                pass
            return None

    async def _bind_shortcuts_async(self, iface=None) -> None:
        """Bind current mappings as portal shortcuts."""
        if not self._session_path or not self._bus:
            return

        if iface is None:
            try:
                introspection = await self._bus.introspect(_PORTAL_BUS, _PORTAL_PATH)
                proxy = self._bus.get_proxy_object(_PORTAL_BUS, _PORTAL_PATH, introspection)
                iface = proxy.get_interface(_PORTAL_IFACE)
            except Exception:
                logger.warning("Failed to get portal interface for rebind")
                return

        # Build shortcuts array: list of (id, properties_dict)
        shortcuts = []
        for i, m in enumerate(self._mappings):
            shortcut_id = f"nixchirp_{i}"
            m.shortcut_id = shortcut_id

            desc = f"{m.action}: {m.target}" if m.target else m.action
            props: dict[str, Variant] = {
                "description": Variant("s", desc),
            }
            shortcuts.append((shortcut_id, props))

        if not shortcuts:
            logger.info("No shortcuts to bind")
            return

        request_token = self._next_token()
        try:
            result = await self._call_with_response(
                iface, "bind_shortcuts",
                self._session_path,
                shortcuts,
                "",  # parent_window (empty = no parent)
                {
                    "handle_token": Variant("s", request_token),
                },
            )

            if result is None:
                logger.warning("BindShortcuts got no response")
                self._status = "Binding failed"
                return

            response_code, response_data = result
            if response_code != 0:
                logger.warning("BindShortcuts denied (code %d)", response_code)
                self._status = "Binding denied"
                return

            # Update trigger descriptions from response
            bound = response_data.get("shortcuts", Variant("a(sa{sv})", [])).value
            for shortcut_id, props in bound:
                trigger = props.get("trigger_description", Variant("s", "")).value
                for m in self._mappings:
                    if m.shortcut_id == shortcut_id:
                        m.trigger = trigger
                        break

            logger.info("Portal shortcuts bound: %d shortcuts", len(shortcuts))
            self._status = "Active"

        except Exception:
            logger.warning("Failed to bind shortcuts", exc_info=True)
            self._status = "Binding error"

    def bind_shortcuts(self) -> None:
        """Trigger shortcut binding (shows system dialog).

        Call from the main thread — schedules the bind on the async loop.
        """
        if not self._loop or not self._running:
            return
        asyncio.run_coroutine_threadsafe(
            self._bind_shortcuts_async(), self._loop
        )

    def _on_activated(self, session_handle: str, shortcut_id: str, timestamp: int, options: dict) -> None:
        """Portal signal: a global shortcut was pressed."""
        if session_handle != self._session_path:
            return

        for mapping in self._mappings:
            if mapping.shortcut_id != shortcut_id:
                continue

            if mapping.action == "set_group" and mapping.target:
                self._event_queue.put_nowait(
                    StateEvent(
                        EventType.GROUP_CHANGE,
                        target_state=mapping.target,
                    )
                )
                logger.debug("Portal shortcut %s → set_group '%s'",
                             shortcut_id, mapping.target)
            elif mapping.action == "set_state" and mapping.target:
                self._event_queue.put_nowait(
                    StateEvent(
                        EventType.HOTKEY_TRIGGER,
                        target_state=mapping.target,
                    )
                )
                logger.debug("Portal shortcut %s → set_state '%s'",
                             shortcut_id, mapping.target)
            break

    def _on_deactivated(self, session_handle: str, shortcut_id: str, timestamp: int, options: dict) -> None:
        """Portal signal: a global shortcut was released."""
        if session_handle != self._session_path:
            return

        # For momentary group changes, release reverts to default
        for mapping in self._mappings:
            if mapping.shortcut_id != shortcut_id:
                continue

            if mapping.action == "set_group":
                self._event_queue.put_nowait(
                    StateEvent(EventType.GROUP_CHANGE, target_state="")
                )
                logger.debug("Portal shortcut %s released → revert group",
                             shortcut_id)
            break

    def stop(self) -> None:
        """Stop the portal session gracefully."""
        self._running = False
        # Signal the shutdown event to wake _portal_main
        if self._shutdown_event and self._loop:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._loop = None
        self._bus = None
        self._session_path = ""
        self._portal_available = False
        self._shutdown_event = None
        self._status = "Stopped"
        logger.info("Hotkey portal stopped")
