"""Constants for the Solaire Intelligence integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "solaire_intelligence"

# The one HTTP endpoint the integration talks to. It trades an integration key
# for a broker account and the list of devices the key covers.
API_URL: Final = "https://zgwwgtkfqmsqklqnujms.supabase.co/functions/v1/ha-connect"
PORTAL_URL: Final = "https://portal.solaire-intelligence.co.za"
KEY_PAGE_URL: Final = f"{PORTAL_URL}/home-assistant"

CONF_API_KEY: Final = "api_key"
CONF_TRANSPORT: Final = "transport"
TRANSPORT_TCP: Final = "tcp"
TRANSPORT_WS: Final = "websockets"

KEY_PREFIX: Final = "si_ha_"

DEFAULT_REFRESH_SECONDS: Final = 1800
MANUFACTURER: Final = "Solaire Intelligence"

# Wire product name -> what a person calls it. "gate" is the MQTT product
# string SI Access still uses on the wire.
PRODUCT_NAMES: Final = {
    "gateway": "SI Gateway",
    "pool": "SI Pool",
    "water": "SI Water",
    "relay": "SI Relay",
    "gate": "SI Access",
    "switch": "SI Switch",
    "geyser": "SI Geyser",
    "yield": "SI Well-IQ",
}

PLATFORMS: Final = ["binary_sensor", "button", "number", "select", "sensor", "switch", "text"]

# Topics that exist for onboarding or the device's own setup page. Never
# surfaced, catalogued or not.
HIDDEN_OBJECT_PATTERNS: Final = (
    r"^setup__", r"^si_claim", r"^si_wifi_networks$", r"^factory_reset",
    r"^restart", r"^safe_mode", r"^si_identity$", r"^change_wifi", r"^reset_to_factory",
)
DIAGNOSTIC_OBJECT_PATTERNS: Final = (
    r"^si_serial$", r"^si_firmware", r"^si_ota", r"^wifi_", r"^ip_address$",
    r"^uptime", r"^si_build", r"^ssid$", r"^mac", r"^esphome_version$", r"_rssi$",
    r"^si_fw", r"^firmware", r"^si_heap", r"^si_loop", r"^si_last_reset", r"^si_uptime",
    r"^si_wifi",
)
