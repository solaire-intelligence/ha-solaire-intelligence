"""Base entity and the plumbing every platform shares."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import EntitySpec
from .hub import SIHub, signal_availability, signal_new_entity, signal_state

READ_ONLY_PLATFORMS = {"sensor", "binary_sensor"}


def setup_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: str,
    factory: Callable[[SIHub, str, EntitySpec], Entity],
) -> None:
    """Create entities for this platform as the hub discovers them."""
    hub: SIHub = entry.runtime_data
    created: set[str] = set()

    @callback
    def _new(prefix: str, spec: EntitySpec) -> None:
        uid = unique_id(prefix, spec)
        if uid in created:
            return
        created.add(uid)
        async_add_entities([factory(hub, prefix, spec)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, signal_new_entity(entry.entry_id, platform), _new)
    )


def unique_id(prefix: str, spec: EntitySpec) -> str:
    # si/6194e0/gateway/02 + sensor/inverter_battery_soc
    return f"{prefix.replace('/', '_')}_{spec.wire_domain}_{spec.object_id}"


class SIEntity(Entity):
    """One topic on one device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: SIHub, prefix: str, spec: EntitySpec) -> None:
        self.hub = hub
        self.prefix = prefix
        self.spec = spec
        meta = spec.meta
        self._attr_unique_id = unique_id(prefix, spec)
        self._attr_name = spec.name
        self._attr_device_info = hub.device_info(prefix)
        if icon := meta.get("icon"):
            self._attr_icon = icon
        category = meta.get("entity_category")
        if category == "config" and spec.platform in READ_ONLY_PLATFORMS:
            # HA forbids config on read-only platforms; a number the key may not
            # change lands here as a sensor.
            category = "diagnostic"
        if category in ("config", "diagnostic"):
            self._attr_entity_category = EntityCategory(category)
        if meta.get("disabled_by_default"):
            self._attr_entity_registry_enabled_default = False

    @property
    def raw(self) -> str | None:
        return self.hub.states.get((self.prefix, self.spec.key))

    @property
    def available(self) -> bool:
        return self.hub.available(self.prefix) and (
            self.spec.platform == "button" or self.raw is not None
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_state(self.hub.entry.entry_id, self.prefix, self.spec.key),
                self._on_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_availability(self.hub.entry.entry_id), self._on_update
            )
        )
        self._on_update()

    @callback
    def _on_update(self) -> None:
        self._parse()
        self.async_write_ha_state()

    @callback
    def _parse(self) -> None:
        """Turn self.raw into _attr_* state. Overridden per platform."""

    async def _send(self, payload: str) -> None:
        try:
            await self.hub.async_command(self.prefix, self.spec, payload)
        except PermissionError as err:
            raise HomeAssistantError(
                f"{self.spec.name} is read-only with this integration key"
            ) from err
        except ConnectionError as err:
            raise HomeAssistantError("Not connected to Solaire Intelligence") from err


def as_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf from the device
        return None
    return f


def enum_or_none(enum_cls, value: Any):
    if value is None:
        return None
    try:
        return enum_cls(str(value).lower())
    except ValueError:
        return None
