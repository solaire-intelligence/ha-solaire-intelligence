"""Solaire Intelligence — SI devices in Home Assistant, from anywhere.

The integration key from the SI portal is exchanged for a broker account
scoped to exactly what that person may see and do. No local broker, no
port-forwarding, no reflashing: the devices keep talking to the SI platform
and Home Assistant joins as one more (revocable) viewer.
"""
from __future__ import annotations

from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval

from .api import SIApiError, SIAuthError, async_connect
from .catalog import load_catalog
from .const import CONF_API_KEY, PLATFORMS
from .hub import SIHub

_LOGGER = logging.getLogger(__name__)

type SIConfigEntry = ConfigEntry[SIHub]


async def async_setup_entry(hass: HomeAssistant, entry: SIConfigEntry) -> bool:
    api_key = entry.data[CONF_API_KEY]
    try:
        info = await async_connect(hass, api_key)
    except SIAuthError as err:
        raise ConfigEntryAuthFailed("The integration key was revoked or is invalid") from err
    except SIApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    if not info.devices:
        _LOGGER.warning(
            "Key %s covers no devices you can currently see — check its plants in the SI portal",
            info.label,
        )

    catalog = await hass.async_add_executor_job(load_catalog)
    hub = SIHub(hass, entry, info, catalog)
    entry.runtime_data = hub
    hub.async_register_devices()
    hub.async_cleanup_stale_devices()

    checking = False
    last_refusal_check = 0.0

    async def _check_key() -> None:
        """Ask the platform whether the key still stands; reload or re-auth."""
        nonlocal checking
        if checking:
            return
        checking = True
        try:
            fresh = await async_connect(hass, api_key)
        except SIAuthError:
            _LOGGER.warning("Integration key %s is no longer valid", info.label)
            entry.async_start_reauth(hass)
            return
        except SIApiError as err:
            _LOGGER.debug("Key check skipped: %s", err)
            return
        finally:
            checking = False
        if fresh.signature() != info.signature() or fresh.broker != info.broker:
            _LOGGER.info("Devices or permissions changed for %s — reloading", info.label)
            hass.config_entries.async_schedule_reload(entry.entry_id)

    @callback
    def _on_auth_refused() -> None:
        # A new key needs one broker sync (<= 60 s) before the broker knows it,
        # so a refusal right after setup is normal. A refusal on a key the
        # platform still accepts is left to paho's reconnect backoff. At most
        # one platform check every five minutes, however often the broker says no.
        nonlocal last_refusal_check
        now = time.monotonic()
        if now - last_refusal_check < 300:
            return
        last_refusal_check = now
        hass.async_create_task(_check_key())

    hub.on_auth_refused = _on_auth_refused

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(
        async_track_time_interval(
            hass, lambda _now: hass.async_create_task(_check_key()),
            timedelta(seconds=info.refresh_seconds),
        )
    )
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    await hub.async_start()
    return True


async def _options_updated(hass: HomeAssistant, entry: SIConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SIConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
