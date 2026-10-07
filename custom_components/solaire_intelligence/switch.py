"""Switches the key is allowed to operate."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import EntitySpec
from .entity import SIEntity, enum_or_none, setup_platform
from .hub import SIHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, "switch", SISwitch)


class SISwitch(SIEntity, SwitchEntity):
    def __init__(self, hub: SIHub, prefix: str, spec: EntitySpec) -> None:
        super().__init__(hub, prefix, spec)
        self._attr_device_class = enum_or_none(SwitchDeviceClass, spec.meta.get("device_class"))

    @callback
    def _parse(self) -> None:
        raw = (self.raw or "").strip().upper()
        self._attr_is_on = True if raw == "ON" else False if raw == "OFF" else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send("ON")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send("OFF")
