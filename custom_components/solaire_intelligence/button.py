"""Buttons — gate triggers, resets. Offered only for builds the catalog knows,
because ESPHome buttons publish no state topic to discover them from."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import SIEntity, setup_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, "button", SIButton)


class SIButton(SIEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self._send("PRESS")
