"""End-to-end: real Mosquitto, real paho, mocked ha-connect."""
from __future__ import annotations

import asyncio
import time

import paho.mqtt.client as mqtt
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.solaire_intelligence.const import API_URL, CONF_API_KEY, DOMAIN

from .conftest import HA_PASS, HA_USER

KEY = "si_ha_" + "a" * 64
GW = "si/abc123/gateway/01"
GATE = "si/abc123/gate/01"


def connect_body(port: int, gate_writable=("button",), scope="control", ws_port=None) -> dict:
    return {
        "api_version": 1,
        "key_id": "key-1",
        "label": "Test HA",
        "scope": scope,
        "broker": {"host": "127.0.0.1", "port": port, "ws_port": ws_port or port, "ws_path": "/mqtt",
                   "username": HA_USER, "password": HA_PASS, "tls": False},
        "plants": [{
            "code": "abc123", "name": "Test Plant",
            "devices": [
                {"product": "gateway", "index": "01", "label": "Test Gateway", "serial": "GATE-2026-08-0001",
                 "firmware_version": "2026.10.07-01", "build": "si-gateway-stock", "phases": 1,
                 "writable": ["button", "switch", "number"]},
                {"product": "gate", "index": "01", "label": "Gate", "serial": "SLGT-2026-06-0001",
                 "firmware_version": "2026.09.22-6", "build": "si-access", "phases": 1,
                 "writable": list(gate_writable)},
            ],
        }],
        "refresh_seconds": 1800,
    }


async def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.1)
    return False


@pytest.fixture(autouse=True)
def _enable_custom(enable_custom_integrations):
    yield


@pytest.fixture
def allow_localhost(socket_enabled):
    yield


async def _setup(hass, aioclient_mock, port, options=None, **kw):
    aioclient_mock.post(API_URL, json=connect_body(port, **kw))
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: KEY}, unique_id="key-1", title="Test HA",
                            options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def publish_device_state(sim):
    sim.pub(f"{GW}/status", "online")
    sim.pub(f"{GW}/sensor/inverter_battery_soc/state", "87")
    sim.pub(f"{GW}/sensor/inverter_total_pv_energy/state", "1234.5")
    sim.pub(f"{GW}/sensor/si_surplus_scale/state", "14")
    sim.pub(f"{GW}/sensor/si_build_name/state", "si-gateway-stock")
    sim.pub(f"{GW}/sensor/si_ota_status/state", "up to date (2026.10.07-01)")
    sim.pub(f"{GW}/switch/si_battery_boost/state", "OFF")
    sim.pub(f"{GW}/number/si_boost_duration/state", "60")
    sim.pub(f"{GW}/select/inverter_energy_pattern/state", "Load First")
    sim.pub(f"{GW}/text/setup__client_id/state", "")       # must stay hidden
    sim.pub(f"{GW}/sensor/brand_new_thing/state", "42.5")   # not in catalog
    sim.pub(f"{GATE}/status", "online")
    sim.pub(f"{GATE}/sensor/gate_state/state", "Closed")
    sim.pub(f"{GATE}/binary_sensor/gate_open/state", "OFF")
    sim.pub(f"{GATE}/number/sequence_delay/state", "15")
    sim.pub(f"{GATE}/sensor/si_build_name/state", "si-access")


async def test_end_to_end(hass: HomeAssistant, aioclient_mock, broker, sim, allow_localhost):
    publish_device_state(sim)
    entry = await _setup(hass, aioclient_mock, broker["port"])
    assert entry.state is ConfigEntryState.LOADED

    ok = await wait_for(lambda: hass.states.get("sensor.si_gateway_inverter_battery_soc") is not None
                        and hass.states.get("button.si_access_gate_trigger") is not None)
    assert ok, sorted(hass.states.async_entity_ids())

    # Entity ids line up with the ESPHome-native ones the public dashboards use.
    soc = hass.states.get("sensor.si_gateway_inverter_battery_soc")
    assert soc.state == "87.0"
    assert soc.attributes["unit_of_measurement"] == "%"
    assert soc.attributes["device_class"] == "battery"

    energy = hass.states.get("sensor.si_gateway_inverter_total_pv_energy")
    assert energy.attributes["state_class"] == "total_increasing"     # Energy dashboard ready
    assert energy.attributes["device_class"] == "energy"

    assert hass.states.get("sensor.si_access_gate_state").state == "Closed"
    assert hass.states.get("binary_sensor.si_access_gate_open").state == "off"

    # Writable on the gateway → real controls.
    assert hass.states.get("switch.si_gateway_si_battery_boost").state == "off"
    assert hass.states.get("number.si_gateway_si_boost_duration") is not None
    # select not writable for this key → read-only sensor, not a select.
    assert hass.states.get("select.si_gateway_inverter_energy_pattern") is None
    assert hass.states.get("sensor.si_gateway_inverter_energy_pattern").state == "Load First"
    # gate numbers are not writable → sensor (and config category demoted).
    assert hass.states.get("number.si_access_sequence_delay") is None
    assert hass.states.get("sensor.si_access_sequence_delay").state == "15.0"

    # Onboarding topics never surface; unknown topics still do.
    assert not [e for e in hass.states.async_entity_ids() if "setup" in e]
    assert hass.states.get("sensor.si_gateway_brand_new_thing").state == "42.5"

    # Devices hang off a plant.
    reg = dr.async_get(hass)
    gw = reg.async_get_device(identifiers={(DOMAIN, GW)})
    plant = reg.async_get_device(identifiers={(DOMAIN, "plant/abc123")})
    assert gw.via_device_id == plant.id
    assert gw.serial_number == "GATE-2026-08-0001"

    # ── commands reach the device ───────────────────────────────────────
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.si_gateway_si_battery_boost"}, blocking=True)
    await hass.services.async_call("number", "set_value",
                                   {"entity_id": "number.si_gateway_si_boost_duration", "value": 120}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.si_access_gate_trigger"}, blocking=True)
    assert await wait_for(lambda: len(sim.received) >= 3)
    assert (f"{GW}/switch/si_battery_boost/command", "ON") in sim.received
    assert (f"{GW}/number/si_boost_duration/command", "120") in sim.received
    assert (f"{GATE}/button/gate_trigger/command", "PRESS") in sim.received

    # State echo from the device updates HA.
    sim.pub(f"{GW}/switch/si_battery_boost/state", "ON")
    assert await wait_for(lambda: hass.states.get("switch.si_gateway_si_battery_boost").state == "on")

    # Device goes offline → its entities go unavailable, the other device's do not.
    sim.pub(f"{GW}/status", "offline")
    assert await wait_for(lambda: hass.states.get("sensor.si_gateway_inverter_battery_soc").state == "unavailable")
    assert hass.states.get("sensor.si_access_gate_state").state == "Closed"
    sim.pub(f"{GW}/status", "online")
    assert await wait_for(lambda: hass.states.get("sensor.si_gateway_inverter_battery_soc").state == "87.0")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_broker_is_the_boundary(broker, sim):
    """Even a hand-rolled client using the key's broker account cannot step
    outside its ACL: no pool, no gate settings, no firmware."""
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rogue")
    c.username_pw_set(HA_USER, HA_PASS)
    got: list[str] = []
    c.on_message = lambda cl, u, m: got.append(m.topic)
    c.connect("127.0.0.1", broker["port"])
    c.subscribe("si/#")
    c.loop_start()
    sim.pub("si/abc123/pool/01/sensor/pool_temperature/state", "24")
    time.sleep(0.5)
    sim.received.clear()
    for topic in ("si/abc123/gate/01/number/sequence_delay/command",
                  "si/abc123/gateway/01/ota/update/command",
                  "si/abc123/pool/01/switch/pump/command"):
        c.publish(topic, "x").wait_for_publish(2)
    c.publish("si/abc123/gateway/01/switch/si_battery_boost/command", "OFF").wait_for_publish(2)
    time.sleep(0.8)
    c.loop_stop()
    c.disconnect()
    assert not any("/pool/" in t for t in got)
    assert sim.received == [("si/abc123/gateway/01/switch/si_battery_boost/command", "OFF")]


async def test_revoked_key_starts_reauth(hass: HomeAssistant, aioclient_mock, broker, allow_localhost):
    aioclient_mock.post(API_URL, status=401, json={"error": "invalid_key"})
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: KEY}, unique_id="key-1")
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == config_entries.SOURCE_REAUTH for f in flows)


async def test_config_flow(hass: HomeAssistant, aioclient_mock, broker):
    aioclient_mock.post(API_URL, json=connect_body(broker["port"]))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "nope"})
    assert result["errors"] == {CONF_API_KEY: "not_a_key"}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.solaire_intelligence.async_setup_entry",
                   lambda *a: asyncio.sleep(0, True))
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: f"  {KEY} "})
    assert result["type"] == "create_entry"
    assert result["title"] == "Test HA (Test Plant)"
    assert result["data"] == {CONF_API_KEY: KEY}


async def test_websocket_transport(hass: HomeAssistant, aioclient_mock, broker, sim, allow_localhost):
    """For networks that block 8883: same session over WebSocket."""
    publish_device_state(sim)
    entry = await _setup(hass, aioclient_mock, broker["port"], ws_port=broker["ws_port"],
                         options={"transport": "websockets"})
    assert await wait_for(lambda: hass.states.get("sensor.si_gateway_inverter_battery_soc") is not None)
    assert hass.states.get("sensor.si_gateway_inverter_battery_soc").state == "87.0"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_read_only_key(hass: HomeAssistant, aioclient_mock, broker, sim, allow_localhost):
    """A monitoring-only key gets no controls at all."""
    publish_device_state(sim)
    body = connect_body(broker["port"], gate_writable=(), scope="read")
    body["plants"][0]["devices"][0]["writable"] = []
    aioclient_mock.post(API_URL, json=body)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_KEY: KEY}, unique_id="key-1")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert await wait_for(lambda: hass.states.get("sensor.si_access_sequence_delay") is not None)
    await asyncio.sleep(0.5)
    ids = hass.states.async_entity_ids()
    assert not [e for e in ids if e.split(".")[0] in ("switch", "number", "select", "button", "text")]
    assert hass.states.get("binary_sensor.si_gateway_si_battery_boost").state == "off"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
