"""Test fixtures: a real Mosquitto with SI-style passwd/ACL, and a device simulator."""
from __future__ import annotations

import getpass
import os
import shutil
import socket
import subprocess
import tempfile
import time

import paho.mqtt.client as mqtt
import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

HA_USER, HA_PASS = "ha-test0001", "ha-secret"
DEV_USER, DEV_PASS = "si-gateway-abc123-01", "dev-secret"

# What integration_key_acl() produces for a Manager-style key on plant abc123:
# full read on the gateway and gate, operate (button+switch) on both, configure
# (number) only on the gateway — and nothing on the pool, which the key does
# not cover at all.
HA_ACL = [
    "topic read si/abc123/gateway/01/#",
    "topic write si/abc123/gateway/01/button/+/command",
    "topic write si/abc123/gateway/01/switch/+/command",
    "topic write si/abc123/gateway/01/number/+/command",
    "topic read si/abc123/gate/01/#",
    "topic write si/abc123/gate/01/button/+/command",
]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def broker(socket_enabled):
    if not shutil.which("mosquitto"):
        pytest.skip("mosquitto not installed")
    d = tempfile.mkdtemp()
    passwd, acl, conf = (os.path.join(d, n) for n in ("passwd", "acl", "mosquitto.conf"))
    open(passwd, "w").close()
    os.chmod(passwd, 0o600)
    for u, p in ((HA_USER, HA_PASS), (DEV_USER, DEV_PASS)):
        subprocess.run(["mosquitto_passwd", "-b", passwd, u, p], check=True)
    with open(acl, "w") as f:
        f.write(f"user {DEV_USER}\ntopic readwrite si/abc123/#\n\n")
        f.write(f"user {HA_USER}\n" + "\n".join(HA_ACL) + "\n")
    os.chmod(acl, 0o600)
    port, ws_port = _free_port(), _free_port()
    with open(conf, "w") as f:
        f.write(f"user {getpass.getuser()}\nper_listener_settings false\nallow_anonymous false\n"
                f"password_file {passwd}\nacl_file {acl}\npersistence false\n"
                f"listener {port} 127.0.0.1\n"
                f"listener {ws_port} 127.0.0.1\nprotocol websockets\n")
    proc = subprocess.Popen(["mosquitto", "-c", conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield {"port": port, "ws_port": ws_port, "passwd": passwd, "acl": acl, "proc": proc}
    proc.terminate()
    proc.wait(5)
    shutil.rmtree(d, ignore_errors=True)


class DeviceSim:
    """Plays the part of SI devices on the broker (as a device account)."""

    def __init__(self, port: int) -> None:
        self.received: list[tuple[str, str]] = []
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sim")
        self.c.username_pw_set(DEV_USER, DEV_PASS)
        self.c.on_message = lambda c, u, m: self.received.append((m.topic, m.payload.decode()))
        self.c.connect("127.0.0.1", port)
        self.c.subscribe("si/abc123/+/+/+/+/command")
        self.c.loop_start()

    def pub(self, topic: str, payload: str, retain: bool = True) -> None:
        self.c.publish(topic, payload, qos=1, retain=retain).wait_for_publish(2)

    def close(self) -> None:
        # clear retained so the next test starts clean
        self.c.loop_stop()
        self.c.disconnect()


@pytest.fixture
def sim(broker):
    s = DeviceSim(broker["port"])
    yield s
    s.close()
