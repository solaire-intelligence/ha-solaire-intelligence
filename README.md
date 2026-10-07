# Solaire Intelligence for Home Assistant

Your SI Gateway, SI Pool, SI Water, SI Relay, SI Access and SI Well-IQ in Home
Assistant — **from anywhere**. Home Assistant does not need to be on the same
network as the devices, and you do not need to run an MQTT broker.

The devices keep running all their automations on board (ECM, timers, Battery
Boost, gate sequences). Home Assistant is a window and a remote control, never
the brain — if Home Assistant or the internet goes down, nothing at the site
changes.

## How it works

1. In the SI app (**Menu → Home Assistant**) create an **integration key**.
   Pick the plants it covers and whether Home Assistant may control them or
   only monitor them.
2. In Home Assistant, install this integration from HACS and paste the key.
3. Home Assistant connects securely (MQTT over TLS) to the Solaire Intelligence
   platform with its own account, scoped to exactly what you can see and do in
   the app. Revoke the key in the app and Home Assistant loses access within a
   minute.

Firmware updates are never done from Home Assistant — use the SI app.

## Install

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/solaire-intelligence/ha-solaire-intelligence`, type
   **Integration**.
2. Search for **Solaire Intelligence**, download, and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Solaire Intelligence**,
   paste your key.

### Manual

Copy `custom_components/solaire_intelligence` into your Home Assistant
`config/custom_components/` folder and restart.

## What you get

- Every value the device publishes, with proper units and device classes —
  inverter energy totals are ready for the **Energy dashboard**.
- Switches, numbers, selects and buttons for what your key may control.
  Settings your key may not change appear as read-only sensors.
- Live online/offline status per device.
- Entity IDs match the ESPHome ones (`sensor.si_gateway_…`, `sensor.si_pool_…`),
  so the dashboards in
  [solaire-home-assistant](https://github.com/solaire-intelligence/solaire-home-assistant)
  work as they are.

## Network

Outbound only: TCP **8883** (MQTT over TLS) and HTTPS. If your network blocks
8883, open the integration's **Configure** and choose **secure WebSocket (9001)**.

## Privacy and security

- The key is shown once in the app and stored only as a hash on our side.
- Each key is its own broker account; nothing is shared with other customers.
- Diagnostics downloads never include the key or broker password.

## For developers

`custom_components/solaire_intelligence/catalog.json` is generated from the
firmware with `tools/build_catalog.sh` (needs ESPHome 2026.8.x and a checkout of
`solaire-esphome`). Regenerate it whenever a product's entities change. Tests
run against a real Mosquitto: `pip install -r requirements_test.txt && pytest`.
