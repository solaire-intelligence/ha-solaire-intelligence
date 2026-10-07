"""Numbers (settings) the key may change."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import EntitySpec
from .entity import SIEntity, as_float, enum_or_none, setup_platform
from .hub import SIHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    setup_platform(hass, entry, async_add_entities, "number", SINumber)


class SINumber(SIEntity, NumberEntity):
    def __init__(self, hub: SIHub, prefix: str, spec: EntitySpec) -> None:
        super().__init__(hub, prefix, spec)
        meta = spec.meta
        self._attr_native_min_value = float(meta["min_value"])
        self._attr_native_max_value = float(meta["max_value"])
        self._attr_native_step = float(meta.get("step") or 1)
        self._attr_native_unit_of_measurement = meta.get("unit_of_measurement") or None
        self._attr_device_class = enum_or_none(NumberDeviceClass, meta.get("device_class"))
        self._attr_mode = enum_or_none(NumberMode, meta.get("mode")) or NumberMode.AUTO

    @callback
    def _parse(self) -> None:
        self._attr_native_value = as_float(self.raw)

    async def async_set_native_value(self, value: float) -> None:
        # ESPHome parses either form; send integers without a trailing .0 so
        # the value reads the same in the broker log as one sent by the app.
        await self._send(str(int(value)) if float(value).is_integer() else repr(float(value)))
