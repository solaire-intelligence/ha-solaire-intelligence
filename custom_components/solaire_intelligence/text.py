"""Text settings (e.g. SI Relay channel names) the key may change."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import SIEntity, setup_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, "text", SIText)


class SIText(SIEntity, TextEntity):
    _attr_native_max = 64

    @callback
    def _parse(self) -> None:
        self._attr_native_value = self.raw

    async def async_set_value(self, value: str) -> None:
        await self._send(value)
