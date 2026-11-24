"""Hermes cron window provider: the plugin's decision window, as Hermes' cron gate reads it.

A Hermes host with ``ctx.register_window_provider(provider)`` holds a due cron job that declares a
``window_class`` until ``provider.current(now)`` says that window is open; ``None`` means the window is
unknown and holds every windowed job (a job with no class, or ``anytime``, always fires).

``WindowProvider.current(now)`` reads the window the asks plan sees (``tools.window_state``: Sleep mode,
the wake event, the last unlock, Glide's focus block and wind-down, focused mode), the same readers
``limitless_window`` uses; no new store, no clock time. ``now`` is only the instant the events are aged
against. The plugin's word for that window becomes the host's class through one table, TO_CRON:

    peak -> peak, trough -> trough, anytime -> anytime, wind_down -> wind_down,
    asleep -> None, focus_block -> None, unknown -> None

Asleep and a focus block (Glide's, or focused mode) hold every windowed job, which in the host's gate is
``None``. ``current`` never raises: any error is ``None``.

Host registration (plugin.register): config ``window_provider`` (default on; false or "off" registers
nothing and logs DISABLED). A host ctx without HOST_METHOD gets nothing and one content-free line,
NO_HOST; a host that raises gets HOST_FAILED and register goes on. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional

from . import decision_window, tools
from .state_reader import StateReader, config, state_dir

logger = logging.getLogger(__name__)

CONFIG_KEY = "window_provider"   # default on; false (or "off") registers nothing
HOST_METHOD = "register_window_provider"   # the host ctx method register looks for (feature detection)
DISABLED = "limitless: window_provider is off in config; the cron window provider is not registered"
NO_HOST = "limitless: the host has no cron window provider API; the window provider is not registered"
HOST_FAILED = "limitless: the host's cron window provider registration failed; register went on"

ASLEEP = "asleep"
FOCUS_BLOCK = "focus_block"   # a window with hold_asks: a Glide focus block, or focused mode

# The plugin's window word -> the host's WindowClass value (None: the gate holds every windowed job).
TO_CRON = {
    "peak": "peak",
    "trough": "trough",
    "anytime": "anytime",
    "wind_down": "wind_down",
    ASLEEP: None,
    FOCUS_BLOCK: None,
    decision_window.UNKNOWN: None,
}


def word(state: Any) -> str:
    """The plugin's word for a ``tools.window_state`` result: asleep, focus_block, an open class or unknown."""
    if isinstance(state, dict):
        return ASLEEP if state.get("value") == ASLEEP else decision_window.UNKNOWN
    if not isinstance(state, decision_window.WindowState):
        return decision_window.UNKNOWN
    if state.hold_asks:
        return FOCUS_BLOCK
    if state.cls in decision_window.WINDOW_CLASSES and state.confidence >= decision_window.MIN_CONFIDENCE:
        return state.cls
    return decision_window.UNKNOWN


def read_word(now: float) -> str:
    """The plugin's window word at epoch ``now`` from the configured state dir (and Glide, if configured)."""
    bands = config().get("window_bands")
    return word(tools.window_state(StateReader(state_dir()), now, bands if isinstance(bands, dict) else None))


class WindowProvider:
    """Hermes' cron ``WindowProvider``: ``current(now)`` is a host WindowClass value or None; never raises."""

    def __init__(self, read: Optional[Callable[[float], str]] = None):
        self._read = read or read_word

    def current(self, now: datetime) -> Optional[str]:
        try:
            return TO_CRON.get(self._read(now.timestamp()))
        except Exception:  # noqa: BLE001 - the host's cron tick must never see a plugin error
            return None


def enabled(cfg: Any) -> bool:
    """On unless config ``window_provider`` is false or \"off\"."""
    v = cfg.get(CONFIG_KEY, True) if isinstance(cfg, dict) else True
    return not (v is False or (isinstance(v, str) and v.strip().lower() in ("off", "false")))


def register(ctx, cfg: Optional[dict] = None) -> None:
    """Offer one WindowProvider to a host whose ctx has register_window_provider, unless config turns it off.
    Off, or a host without the method: nothing registered and one content-free line. Never raises."""
    try:
        on = enabled(config() if cfg is None else cfg)
    except Exception:  # noqa: BLE001 - config is best effort; the default is on
        on = True
    if not on:
        logger.info(DISABLED)
        return
    method = getattr(ctx, HOST_METHOD, None)
    if not callable(method):
        logger.info(NO_HOST)
        return
    try:
        method(WindowProvider())
    except Exception:  # noqa: BLE001 - a host's provider API must never break plugin registration
        logger.warning(HOST_FAILED)
