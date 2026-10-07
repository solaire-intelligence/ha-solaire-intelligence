"""Selects the key may change."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import EntitySpec
from .entity import SIEntity, setup_platform
from .hub import SIHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, "select", SISelect)


class SISelect(SIEntity, SelectEntity):
    def __init__(self, hub: SIHub, prefix: str, spec: EntitySpec) -> None:
        super().__init__(hub, prefix, spec)
        self._attr_options = [str(o) for o in spec.meta.get("options", [])]

    @callback
    def _parse(self) -> None:
        raw = self.raw
        self._attr_current_option = raw if raw in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self._send(option)
