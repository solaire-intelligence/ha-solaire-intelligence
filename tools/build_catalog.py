#!/usr/bin/env python3
"""Build the entity catalog the integration ships with.

Input: the fully-resolved output of `esphome config <target>.yaml` for each
product target in solaire-esphome. Output: catalog.json — for every product,
every entity the firmware publishes over MQTT, keyed by "<domain>/<object_id>"
exactly as it appears in the topic tree, with the metadata Home Assistant
needs (name, unit, device class, state class, min/max/step, options...).

Why from `esphome config` and not the raw YAML: the gateway's inverter
entities come from a remote package (merv-gif/SI-gateway) and substitutions,
!extend and packages are only resolved by ESPHome itself.

Usage (from solaire-esphome, ESPHome 2026.8.x — see README):
    for t in si-gateway-node si-gateway-node-3p si-pool si-water si-relay si-access si-yield; do
        esphome config targets/$t.yaml > /tmp/cfg-$t.yaml
    done
    python3 tools/build_catalog.py \
        gateway=/tmp/cfg-si-gateway-node.yaml gateway=/tmp/cfg-si-gateway-node-3p.yaml \
        pool=/tmp/cfg-si-pool.yaml water=/tmp/cfg-si-water.yaml relay=/tmp/cfg-si-relay.yaml \
        gate=/tmp/cfg-si-access.yaml yield=/tmp/cfg-si-yield.yaml \\
        legacy:gate=/tmp/cfg-si-gate-6194e0.yaml legacy:switch=/tmp/cfg-si-switch-6194e0.yaml ...

A `legacy:` source is a V1 / per-site build still in the field. Its entities
only fill in metadata the current firmware does not define, and its buttons
are offered only to devices reporting that exact build name.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "solaire_intelligence" / "catalog.json"

# The domains the integration drives. Lights are left out on purpose: on every
# SI product the only light is the status LED, which belongs to the device.
DOMAINS = ["sensor", "binary_sensor", "text_sensor", "switch", "number", "select", "button", "text"]

# ESPHome publishes a text_sensor under the "sensor" topic segment
# (MQTT_COMPONENT_TYPE(MQTTTextSensor, "sensor") in mqtt_text_sensor.cpp), so
# the catalog key uses the WIRE domain and records the real kind separately.
WIRE_DOMAIN = {"text_sensor": "sensor"}

# Entities that exist for onboarding / the device's own web page. They are
# meaningless (or hazardous) to drive from Home Assistant.
HIDE_PATTERNS = [
    r"^setup__", r"^si_claim", r"^si_wifi_networks$", r"^factory_reset",
    r"^restart", r"^safe_mode", r"^si_identity$", r"^change_wifi", r"^reset_to_factory",
]
# Kept, but tucked into the diagnostic section of the device page.
DIAGNOSTIC_PATTERNS = [
    r"^si_serial$", r"^si_firmware", r"^si_ota", r"^wifi_", r"^ip_address$",
    r"^uptime", r"^si_build", r"^ssid$", r"^mac", r"^esphome_version$", r"_rssi$",
    r"^si_fw", r"^firmware",
]


class Loader(yaml.SafeLoader):
    pass


def _any_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


Loader.add_multi_constructor("!", _any_tag)


def object_id(name: str) -> str:
    """Mirror EntityBase::write_object_id_to() in ESPHome 2026.x."""
    out = []
    for c in name:
        c = "_" if c == " " else (c.lower() if "A" <= c <= "Z" else c)
        out.append(c if (c in "-_" or c.isdigit() or "a" <= c <= "z") else "_")
    return "".join(out)


def truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "yes", "on", "1")


def pick(entity: dict, domain: str) -> dict:
    meta: dict = {"name": entity["name"]}
    for key in ("unit_of_measurement", "device_class", "state_class", "icon",
                "accuracy_decimals", "entity_category", "mode", "options",
                "min_value", "max_value", "step", "optimistic"):
        if key in entity and entity[key] not in (None, "", []):
            meta[key] = entity[key]
    if truthy(entity.get("disabled_by_default", False)):
        meta["disabled_by_default"] = True
    # number: ESPHome publishes these under `step`/`min_value`/`max_value`
    for k in ("min_value", "max_value", "step"):
        if k in meta:
            try:
                meta[k] = float(meta[k])
            except (TypeError, ValueError):
                meta.pop(k)
    return meta


def entities_from(cfg: dict) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for domain in DOMAINS:
        for ent in cfg.get(domain) or []:
            if not isinstance(ent, dict):
                continue
            name = ent.get("name")
            if not name or truthy(ent.get("internal", False)):
                continue
            # mqtt can be switched off per entity
            if ent.get("state_topic") is not None and str(ent.get("state_topic")).lower() in ("", "none", "null"):
                continue
            oid = object_id(str(name))
            if any(re.search(p, oid) for p in HIDE_PATTERNS):
                continue
            meta = pick(ent, domain)
            if "entity_category" not in meta and any(re.search(p, oid) for p in DIAGNOSTIC_PATTERNS):
                meta["entity_category"] = "diagnostic"
            if domain == "text_sensor":
                meta["kind"] = "text"
            key = f"{WIRE_DOMAIN.get(domain, domain)}/{oid}"
            if key in found and found[key].get("kind") != meta.get("kind"):
                print(f"  ! collision on {key} — keeping the first", file=sys.stderr)
                continue
            found[key] = meta
    return found


def main(argv: list[str]) -> int:
    products: dict[str, dict[str, dict]] = {}
    legacy: dict[str, dict[str, dict]] = {}
    builds: dict[str, dict] = {}
    sources: dict[str, list[str]] = {}
    for arg in argv:
        spec, _, path = arg.partition("=")
        is_legacy = spec.startswith("legacy:")
        product = spec.split(":", 1)[1] if is_legacy else spec
        cfg = yaml.load(Path(path).read_text(), Loader=Loader)
        build = str((cfg.get("esphome") or {}).get("name") or "")
        ents = entities_from(cfg)
        (legacy if is_legacy else products).setdefault(product, {}).update(ents)
        sources.setdefault(product, []).append(f"{'legacy ' if is_legacy else ''}{Path(path).name} ({build})")
        # Buttons publish no state topic, so the integration cannot discover
        # them from traffic. It creates them only for builds listed here.
        if build and not (is_legacy and build in builds):
            builds[build] = {
                "product": product,
                "buttons": {k: v for k, v in sorted(ents.items()) if k.startswith("button/")},
            }
        print(f"{'L' if is_legacy else ' '} {product:8s} {build:24s} {len(ents):4d} entities")
    # Legacy only fills in what the current firmware does not define.
    for product, ents in legacy.items():
        for key in list(ents):
            if key in products.get(product, {}):
                del ents[key]
    out = {
        "_note": "Generated by tools/build_catalog.py from `esphome config` output. Do not hand-edit.",
        "_sources": sources,
        "products": {p: dict(sorted(v.items())) for p, v in sorted(products.items())},
        "legacy": {p: dict(sorted(v.items())) for p, v in sorted(legacy.items())},
        "builds": dict(sorted(builds.items())),
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {OUT}: {sum(len(v) for v in products.values())} current, "
          f"{sum(len(v) for v in legacy.values())} legacy-only, {len(builds)} builds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
