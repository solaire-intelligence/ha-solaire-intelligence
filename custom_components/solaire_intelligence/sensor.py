"""Sensors: numeric and text state topics, plus anything the key may only read."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import EntitySpec
from .entity import SIEntity, as_float, enum_or_none, setup_platform
from .hub import SIHub

TEXT_MAX = 255


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, "sensor", SISensor)


class SISensor(SIEntity, SensorEntity):
    def __init__(self, hub: SIHub, prefix: str, spec: EntitySpec) -> None:
        super().__init__(hub, prefix, spec)
        meta = spec.meta
        if spec.text:
            return
        self._attr_native_unit_of_measurement = meta.get("unit_of_measurement") or None
        self._attr_device_class = enum_or_none(SensorDeviceClass, meta.get("device_class"))
        self._attr_state_class = enum_or_none(SensorStateClass, meta.get("state_class"))
        if (dec := meta.get("accuracy_decimals")) is not None:
            try:
                self._attr_suggested_display_precision = int(dec)
            except (TypeError, ValueError):
                pass
        # A number or select shown read-only: no state class, it is a setting.
        if spec.wire_domain != "sensor":
            self._attr_state_class = None

    @callback
    def _parse(self) -> None:
        raw = self.raw
        if raw is None:
            self._attr_native_value = None
        elif self.spec.text:
            self._attr_native_value = raw[:TEXT_MAX]
        else:
            self._attr_native_value = as_float(raw)
