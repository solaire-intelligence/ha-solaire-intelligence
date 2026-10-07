"""Decide what Home Assistant entity a published MQTT topic becomes.

catalog.json is generated from the firmware itself (tools/build_catalog.py)
and gives names, units, device classes and number/select limits for every V2
entity. Topics it does not know — V1 devices, a firmware newer than this
release — still become entities, with a name derived from the object id, so
nothing a device publishes is silently lost.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from .const import DIAGNOSTIC_OBJECT_PATTERNS, HIDDEN_OBJECT_PATTERNS

CATALOG_PATH = Path(__file__).parent / "catalog.json"


@dataclass(frozen=True)
class Catalog:
    products: dict[str, dict[str, dict[str, Any]]]
    legacy: dict[str, dict[str, dict[str, Any]]]
    builds: dict[str, dict[str, Any]]

    def meta(self, product: str, key: str) -> dict[str, Any] | None:
        return self.products.get(product, {}).get(key) or self.legacy.get(product, {}).get(key)

    def buttons(self, build: str | None, product: str) -> dict[str, dict[str, Any]]:
        """Buttons publish no state, so they are offered only for a known build."""
        entry = self.builds.get(build or "")
        if not entry or entry.get("product") != product:
            return {}
        return entry.get("buttons", {})


def load_catalog() -> Catalog:
    """Blocking: call from an executor."""
    raw = json.loads(CATALOG_PATH.read_text())
    return Catalog(raw.get("products", {}), raw.get("legacy", {}), raw.get("builds", {}))


@dataclass(frozen=True)
class EntitySpec:
    """Everything a platform needs to build one entity."""

    platform: str            # HA platform: sensor, binary_sensor, switch, ...
    wire_domain: str         # topic segment: sensor, switch, number, ...
    object_id: str
    name: str
    meta: dict[str, Any] = field(default_factory=dict)
    text: bool = False       # sensor platform: string state rather than numeric
    known: bool = True       # came from the catalog

    @property
    def key(self) -> str:
        return f"{self.wire_domain}/{self.object_id}"


def _humanise(object_id: str) -> str:
    words = [w for w in object_id.split("_") if w]
    if not words:
        return object_id
    out = " ".join(words)
    out = re.sub(r"\b(si|ecm|soc|pv|ota|ip|mac|ssid|ac|dc)\b", lambda m: m.group(1).upper(), out)
    return out[0].upper() + out[1:]


def resolve(
    catalog: Catalog,
    product: str,
    wire_domain: str,
    object_id: str,
    writable: frozenset[str],
    first_payload: str,
) -> EntitySpec | None:
    """Map one topic to an entity, or None to ignore it."""
    if any(re.search(p, object_id) for p in HIDDEN_OBJECT_PATTERNS):
        return None

    meta = catalog.meta(product, f"{wire_domain}/{object_id}")
    # Older ESPHome published text sensors under text_sensor/, newer under sensor/.
    if meta is None and wire_domain == "text_sensor":
        meta = catalog.meta(product, f"sensor/{object_id}")
    known = meta is not None
    meta = dict(meta or {})
    name = meta.get("name") or _humanise(object_id)
    if not known and any(re.search(p, object_id) for p in DIAGNOSTIC_OBJECT_PATTERNS):
        meta["entity_category"] = "diagnostic"

    def spec(platform: str, text: bool = False) -> EntitySpec:
        return EntitySpec(platform, wire_domain, object_id, name, meta, text, known)

    if wire_domain in ("sensor", "text_sensor"):
        if wire_domain == "text_sensor" or meta.get("kind") == "text":
            return spec("sensor", text=True)
        if known:
            return spec("sensor")
        # Unknown: a sensor that is not numeric on first sight is a text sensor.
        return spec("sensor", text=not _is_number(first_payload))

    if wire_domain == "binary_sensor":
        return spec("binary_sensor")

    if wire_domain == "switch":
        return spec("switch") if "switch" in writable else spec("binary_sensor")

    if wire_domain == "number":
        if "number" in writable and "min_value" in meta and "max_value" in meta:
            return spec("number")
        return spec("sensor", text=not _is_number(first_payload))

    if wire_domain == "select":
        if "select" in writable and meta.get("options"):
            return spec("select")
        return spec("sensor", text=True)

    if wire_domain == "text":
        return spec("text") if "text" in writable else spec("sensor", text=True)

    if wire_domain == "button":
        return spec("button") if "button" in writable else None

    # light (status LEDs), ota, debug and anything newer: not exposed.
    return None


def _is_number(payload: str) -> bool:
    try:
        float(payload)
    except (TypeError, ValueError):
        return payload.strip().lower() in ("nan", "")
    return True
