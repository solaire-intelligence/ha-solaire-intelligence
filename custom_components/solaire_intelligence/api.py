"""The one HTTP call: trade an integration key for broker access + device list."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_URL, DEFAULT_REFRESH_SECONDS

_LOGGER = logging.getLogger(__name__)


class SIApiError(Exception):
    """The platform could not be reached or answered badly."""


class SIAuthError(SIApiError):
    """The key is unknown, revoked, or its account is suspended."""


@dataclass(frozen=True)
class SIDevice:
    """One device the key may see."""

    site: str
    plant_name: str
    product: str
    index: str
    label: str | None = None
    serial: str | None = None
    firmware_version: str | None = None
    build: str | None = None
    writable: frozenset[str] = field(default_factory=frozenset)

    @property
    def prefix(self) -> str:
        """MQTT topic prefix, exactly as the firmware publishes it."""
        return f"si/{self.site}/{self.product}/{self.index}"


@dataclass(frozen=True)
class SIBroker:
    host: str
    port: int
    ws_port: int
    ws_path: str
    username: str
    password: str
    tls: bool = True


@dataclass(frozen=True)
class SIConnectInfo:
    key_id: str
    label: str
    scope: str
    broker: SIBroker
    devices: tuple[SIDevice, ...]
    plants: dict[str, str]
    refresh_seconds: int

    def signature(self) -> tuple:
        """What, if it changes, means the entry must reload."""
        return (
            self.scope,
            tuple(sorted((d.prefix, tuple(sorted(d.writable))) for d in self.devices)),
        )


def parse_connect(body: dict[str, Any]) -> SIConnectInfo:
    """Turn the ha-connect response into typed objects."""
    b = body["broker"]
    broker = SIBroker(
        host=b["host"],
        port=int(b.get("port", 8883)),
        ws_port=int(b.get("ws_port", 9001)),
        ws_path=b.get("ws_path", "/mqtt"),
        username=b["username"],
        password=b["password"],
        tls=bool(b.get("tls", True)),
    )
    devices: list[SIDevice] = []
    plants: dict[str, str] = {}
    for plant in body.get("plants") or []:
        code = plant["code"]
        plants[code] = plant.get("name") or code
        for d in plant.get("devices") or []:
            devices.append(
                SIDevice(
                    site=code,
                    plant_name=plants[code],
                    product=str(d["product"]),
                    index=str(d["index"]),
                    label=(d.get("label") or "").strip() or None,
                    serial=d.get("serial"),
                    firmware_version=d.get("firmware_version"),
                    build=d.get("build"),
                    writable=frozenset(d.get("writable") or []),
                )
            )
    return SIConnectInfo(
        key_id=str(body.get("key_id", "")),
        label=str(body.get("label") or "Home Assistant"),
        scope=str(body.get("scope", "read")),
        broker=broker,
        devices=tuple(devices),
        plants=plants,
        refresh_seconds=int(body.get("refresh_seconds") or DEFAULT_REFRESH_SECONDS),
    )


async def async_connect(hass: HomeAssistant, api_key: str, url: str = API_URL) -> SIConnectInfo:
    """Call ha-connect. Raises SIAuthError on a bad key, SIApiError otherwise."""
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(20):
            resp = await session.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={},
            )
            if resp.status == 401:
                raise SIAuthError("integration key rejected")
            if resp.status != 200:
                raise SIApiError(f"ha-connect returned HTTP {resp.status}")
            body = await resp.json()
    except SIApiError:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise SIApiError(f"could not reach Solaire Intelligence: {err}") from err

    try:
        return parse_connect(body)
    except (KeyError, TypeError, ValueError) as err:
        raise SIApiError(f"unexpected response from ha-connect: {err}") from err
