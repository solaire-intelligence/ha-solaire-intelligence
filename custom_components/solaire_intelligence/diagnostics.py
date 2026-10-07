"""Diagnostics download — never includes the key or the broker password."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SIConfigEntry
from .const import CONF_API_KEY

REDACT = {CONF_API_KEY, "password"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SIConfigEntry) -> dict[str, Any]:
    hub = entry.runtime_data
    info = hub.info
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "key": {"label": info.label, "scope": info.scope, "key_id": info.key_id},
        "broker": {
            "host": info.broker.host, "port": info.broker.port, "ws_port": info.broker.ws_port,
            "username": info.broker.username, "connected": hub.connected,
            "auth_refused": hub.auth_refused,
        },
        "devices": [
            {
                "prefix": prefix,
                "name": st.name,
                "build": st.build,
                "online": st.online,
                "writable": sorted(st.device.writable),
                "topics_seen": len(st.seen),
                "buttons_added": st.buttons_added,
            }
            for prefix, st in hub.devices.items()
        ],
    }
