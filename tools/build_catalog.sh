#!/usr/bin/env bash
# Regenerate custom_components/solaire_intelligence/catalog.json from the
# firmware. Run from anywhere; FW points at your solaire-esphome checkout.
# Pin ESPHome to the version the fleet is built with (2026.9 removed
# modbus register_count, which the SI-gateway package still uses).
set -euo pipefail
FW="${FW:-$HOME/Developer/GitHub/solaire-esphome}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
cd "$FW"
cfg() { esphome config "$1" > "$TMP/$(basename "$1" .yaml).yaml"; }
for t in targets/si-gateway-node targets/si-gateway-node-3p targets/si-gateway-node-6194e0 \
         targets/si-pool targets/si-water targets/si-relay targets/si-access targets/si-yield \
         si-gate-6194e0 si-water-6194e0 si-water-58710c si-switch-6194e0 si-gateway-2ad473 \
         si-gateway-3cbaac si-gateway-2abf2f si-gateway-1 si-relay-3cbaac si-pool-6194e0; do
  echo "esphome config $t"; cfg "$t.yaml" 2>/dev/null
done
python3 "$HERE/build_catalog.py" \
  gateway="$TMP/si-gateway-node.yaml" gateway="$TMP/si-gateway-node-3p.yaml" \
  gateway="$TMP/si-gateway-node-6194e0.yaml" \
  pool="$TMP/si-pool.yaml" water="$TMP/si-water.yaml" relay="$TMP/si-relay.yaml" \
  gate="$TMP/si-access.yaml" yield="$TMP/si-yield.yaml" \
  legacy:gate="$TMP/si-gate-6194e0.yaml" legacy:water="$TMP/si-water-6194e0.yaml" \
  legacy:water="$TMP/si-water-58710c.yaml" legacy:switch="$TMP/si-switch-6194e0.yaml" \
  legacy:gateway="$TMP/si-gateway-2ad473.yaml" legacy:gateway="$TMP/si-gateway-3cbaac.yaml" \
  legacy:gateway="$TMP/si-gateway-2abf2f.yaml" legacy:gateway="$TMP/si-gateway-1.yaml" \
  legacy:relay="$TMP/si-relay-3cbaac.yaml" legacy:pool="$TMP/si-pool-6194e0.yaml"
rm -rf "$TMP"
