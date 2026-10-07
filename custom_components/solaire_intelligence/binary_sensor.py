"""Binary sensors — and switches the key may see but not operate."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import EntitySpec
from .entity import SIEntity, enum_or_none, setup_platform
from .hub import SIHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, "binary_sensor", SIBinarySensor)


class SIBinarySensor(SIEntity, BinarySensorEntity):
    def __init__(self, hub: SIHub, prefix: str, spec: EntitySpec) -> None:
        super().__init__(hub, prefix, spec)
        if spec.wire_domain == "binary_sensor":
            self._attr_device_class = enum_or_none(BinarySensorDeviceClass, spec.meta.get("device_class"))
        elif spec.wire_domain == "switch":
            self._attr_device_class = BinarySensorDeviceClass.POWER

    @callback
    def _parse(self) -> None:
        raw = (self.raw or "").strip().upper()
        self._attr_is_on = True if raw == "ON" else False if raw == "OFF" else None
