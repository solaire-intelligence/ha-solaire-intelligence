"""The connection to the Solaire Intelligence broker.

One MQTT session per config entry, authenticated as the key's own broker
account (ha-xxxxxxxx). The broker's ACL — generated from the person's
capabilities in the SI platform — is the real boundary; this file only ever
subscribes to and commands what ha-connect said the key may touch.

Entities are created from traffic: the first time a device publishes a state
topic, it becomes an entity (described by the catalog when the topic is known).
So a 3-phase gateway gets 3-phase entities, a V1 unit gets what it actually
publishes, and nothing is invented for hardware that is not there.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import re
import uuid

import paho.mqtt.client as mqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util.ssl import client_context

from .api import SIConnectInfo, SIDevice
from .catalog import Catalog, EntitySpec, resolve
from .const import (
    CONF_TRANSPORT,
    DOMAIN,
    MANUFACTURER,
    PORTAL_URL,
    PRODUCT_NAMES,
    TRANSPORT_WS,
)

_LOGGER = logging.getLogger(__name__)

# si/<site>/<product>/<index>/<rest...>
TOPIC_RE = re.compile(r"^si/([a-z0-9]{6})/([a-z_]+)/([0-9A-Za-z_-]+)/(.+)$")
STATE_RE = re.compile(r"^([a-z_]+)/([A-Za-z0-9_\-]+)/state$")

# MQTT 3.1.1 CONNACK refusals that mean "these credentials are wrong", as
# opposed to "the broker is busy / unreachable".
AUTH_REFUSALS = {4, 5, 134, 135}


def signal_new_entity(entry_id: str, platform: str) -> str:
    return f"{DOMAIN}_{entry_id}_new_{platform}"


def signal_state(entry_id: str, prefix: str, key: str) -> str:
    return f"{DOMAIN}_{entry_id}_state_{prefix}_{key}"


def signal_availability(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_availability"


@dataclass
class DeviceState:
    device: SIDevice
    name: str
    online: bool | None = None          # from <prefix>/status; None = never heard
    build: str | None = None
    seen: set[str] = field(default_factory=set)
    buttons_added: bool = False


class SIHub:
    """MQTT session + entity bookkeeping for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        info: SIConnectInfo,
        catalog: Catalog,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.info = info
        self.catalog = catalog
        self.connected = False
        self.auth_refused = False
        self.on_auth_refused: Callable[[], None] | None = None
        self.states: dict[tuple[str, str], str] = {}
        self.devices: dict[str, DeviceState] = {}
        self._client: mqtt.Client | None = None

        counts: dict[str, int] = {}
        for d in info.devices:
            counts[d.product] = counts.get(d.product, 0) + 1
        for d in info.devices:
            base = PRODUCT_NAMES.get(d.product, f"SI {d.product.title()}")
            # One of a kind keeps the plain product name, so entity ids come out
            # as sensor.si_gateway_* — the same ids the ESPHome native
            # integration produces and the public dashboards are written for.
            name = base if counts[d.product] == 1 else f"{base} {d.label or d.index}"
            self.devices[d.prefix] = DeviceState(device=d, name=name, build=d.build)

    # ── device registry ──────────────────────────────────────────────────

    @callback
    def async_register_devices(self) -> None:
        reg = dr.async_get(self.hass)
        for code, plant in self.info.plants.items():
            reg.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, f"plant/{code}")},
                manufacturer=MANUFACTURER,
                name=f"{plant} plant",
                model="SI Plant",
                serial_number=code,
                configuration_url=PORTAL_URL,
                entry_type=dr.DeviceEntryType.SERVICE,
            )
        for prefix in self.devices:
            reg.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                **self.device_info(prefix),
            )

    def device_info(self, prefix: str) -> dict:
        st = self.devices[prefix]
        d = st.device
        return {
            "identifiers": {(DOMAIN, prefix)},
            "manufacturer": MANUFACTURER,
            "name": st.name,
            "model": PRODUCT_NAMES.get(d.product, d.product),
            "model_id": st.build or None,
            "serial_number": d.serial,
            "sw_version": d.firmware_version,
            "via_device": (DOMAIN, f"plant/{d.site}"),
            "configuration_url": PORTAL_URL,
        }

    @callback
    def async_cleanup_stale_devices(self) -> None:
        """Remove devices the key no longer covers (revoked share, retired unit)."""
        reg = dr.async_get(self.hass)
        wanted = {(DOMAIN, p) for p in self.devices} | {
            (DOMAIN, f"plant/{c}") for c in self.info.plants
        }
        for dev in dr.async_entries_for_config_entry(reg, self.entry.entry_id):
            if not dev.identifiers & wanted:
                reg.async_update_device(dev.id, remove_config_entry_id=self.entry.entry_id)

    # ── availability ─────────────────────────────────────────────────────

    def available(self, prefix: str) -> bool:
        st = self.devices.get(prefix)
        if not self.connected or st is None:
            return False
        # A device we have state from but no birth message for is treated as
        # online — older firmware does not always retain its status topic.
        return st.online is not False

    # ── MQTT lifecycle ───────────────────────────────────────────────────

    async def async_start(self) -> None:
        self._client = await self.hass.async_add_executor_job(self._build_client)
        await self.hass.async_add_executor_job(self._connect)

    def _build_client(self) -> mqtt.Client:
        b = self.info.broker
        ws = self.entry.options.get(CONF_TRANSPORT) == TRANSPORT_WS
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{b.username}-{uuid.uuid4().hex[:8]}",
            protocol=mqtt.MQTTv311,
            transport="websockets" if ws else "tcp",
            clean_session=True,
        )
        client.username_pw_set(b.username, b.password)
        if b.tls:
            client.tls_set_context(client_context())
        if ws:
            client.ws_set_options(path=b.ws_path)
        client.reconnect_delay_set(min_delay=2, max_delay=120)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def _connect(self) -> None:
        b = self.info.broker
        ws = self.entry.options.get(CONF_TRANSPORT) == TRANSPORT_WS
        assert self._client is not None
        self._client.connect_async(b.host, b.ws_port if ws else b.port, keepalive=60)
        self._client.loop_start()

    async def async_stop(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return

        def _stop() -> None:
            client.disconnect()
            client.loop_stop()

        await self.hass.async_add_executor_job(_stop)

    # paho callbacks run on paho's thread: hop onto the event loop at once.

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            value = getattr(reason_code, "value", None)
            self.hass.loop.call_soon_threadsafe(self._handle_refused, value, str(reason_code))
            return
        for prefix in self.devices:
            client.subscribe(f"{prefix}/#", qos=0)
        self.hass.loop.call_soon_threadsafe(self._set_connected, True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        self.hass.loop.call_soon_threadsafe(self._set_connected, False)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - never let a bad payload kill the thread
            return
        self.hass.loop.call_soon_threadsafe(self._handle_message, msg.topic, payload)

    @callback
    def _set_connected(self, connected: bool) -> None:
        if connected:
            self.auth_refused = False
            _LOGGER.info("Connected to the Solaire Intelligence broker as %s", self.info.broker.username)
        elif self.connected:
            _LOGGER.warning("Lost connection to the Solaire Intelligence broker; retrying")
        self.connected = connected
        async_dispatcher_send(self.hass, signal_availability(self.entry.entry_id))

    @callback
    def _handle_refused(self, value: int | None, text: str) -> None:
        self.connected = False
        if value in AUTH_REFUSALS:
            # A brand-new key reaches the broker on the next sync (<= 60 s), so
            # an early refusal is expected; the owner of this callback checks
            # with the platform whether the key is still valid.
            if not self.auth_refused:
                _LOGGER.info("Broker refused %s (%s)", self.info.broker.username, text)
            self.auth_refused = True
            if self.on_auth_refused:
                self.on_auth_refused()
        else:
            _LOGGER.warning("Broker refused the connection: %s", text)
        async_dispatcher_send(self.hass, signal_availability(self.entry.entry_id))

    # ── messages ─────────────────────────────────────────────────────────

    @callback
    def _handle_message(self, topic: str, payload: str) -> None:
        m = TOPIC_RE.match(topic)
        if not m:
            return
        site, product, index, rest = m.groups()
        prefix = f"si/{site}/{product}/{index}"
        st = self.devices.get(prefix)
        if st is None:
            return

        if rest == "status":
            online = payload.strip().lower() == "online"
            if online != st.online:
                st.online = online
                async_dispatcher_send(self.hass, signal_availability(self.entry.entry_id))
            return

        sm = STATE_RE.match(rest)
        if not sm:
            return
        wire_domain, object_id = sm.groups()
        key = f"{wire_domain}/{object_id}"
        self.states[(prefix, key)] = payload

        if key in ("sensor/si_build_name", "text_sensor/si_build_name") and payload and payload != st.build:
            st.build = payload.strip()
            self._maybe_add_buttons(prefix)

        if key not in st.seen:
            st.seen.add(key)
            spec = resolve(self.catalog, st.device.product, wire_domain, object_id,
                           st.device.writable, payload)
            if spec is not None:
                async_dispatcher_send(
                    self.hass, signal_new_entity(self.entry.entry_id, spec.platform), prefix, spec
                )
            if not st.buttons_added:
                self._maybe_add_buttons(prefix)

        async_dispatcher_send(self.hass, signal_state(self.entry.entry_id, prefix, key))

    @callback
    def _maybe_add_buttons(self, prefix: str) -> None:
        st = self.devices[prefix]
        if st.buttons_added or "button" not in st.device.writable:
            return
        buttons = self.catalog.buttons(st.build, st.device.product)
        if not buttons:
            return
        st.buttons_added = True
        for key, meta in buttons.items():
            _, object_id = key.split("/", 1)
            spec = resolve(self.catalog, st.device.product, "button", object_id,
                           st.device.writable, "")
            if spec is not None:
                async_dispatcher_send(
                    self.hass, signal_new_entity(self.entry.entry_id, "button"), prefix, spec
                )

    # ── commands ─────────────────────────────────────────────────────────

    async def async_command(self, prefix: str, spec: EntitySpec, payload: str) -> None:
        st = self.devices.get(prefix)
        if st is None or spec.wire_domain not in st.device.writable:
            raise PermissionError(f"{spec.key} is read-only for this key")
        if self._client is None:
            raise ConnectionError("not connected")
        topic = f"{prefix}/{spec.wire_domain}/{spec.object_id}/command"
        client = self._client
        await self.hass.async_add_executor_job(client.publish, topic, payload, 0, False)
