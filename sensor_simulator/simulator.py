"""
Sensor simulator.

Runs one "virtual sensor" per warehouse. Each sensor:
  - Generates a diurnal variation via a sine wave
  - Adds small random noise (mimics real sensor tolerance)
  - Occasionally triggers an anomaly scenario
    (e.g. "door left open" -> temperature spikes)
  - Publishes to MQTT topics `warehouse/{warehouse_id}/temperature`
    and `warehouse/{warehouse_id}/humidity`.

Can be run standalone:
    python simulator.py
"""

import json
import math
import random
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt

from config import (
    ANOMALY_DURATION_MAX,
    ANOMALY_DURATION_MIN,
    ANOMALY_PROBABILITY,
    MQTT_HOST,
    MQTT_PORT,
    PUBLISH_INTERVAL_MAX,
    PUBLISH_INTERVAL_MIN,
    WAREHOUSES,
)


@dataclass
class AnomalyState:
    """The currently active anomaly for a warehouse (if any)."""
    active: bool = False
    ends_at: float = 0.0
    scenario: str = ""
    temp_offset: float = 0.0
    humidity_offset: float = 0.0


@dataclass
class WarehouseSensor:
    """Virtual sensor for a single warehouse."""
    warehouse_id: str
    cfg: dict
    anomaly: AnomalyState = field(default_factory=AnomalyState)
    started_at: float = field(default_factory=time.time)

    def _diurnal(self, center: float, amplitude: float) -> float:
        """
        Diurnal sine wave. Modelled as a 24h period but compressed to
        10 minutes so that a full "day cycle" is observable during a
        demo in just a few minutes.
        """
        period_seconds = 600  # 10 min = 1 simulated day
        elapsed = time.time() - self.started_at
        phase = (elapsed % period_seconds) / period_seconds * 2 * math.pi
        return center + amplitude * math.sin(phase)

    def _maybe_trigger_anomaly(self) -> None:
        """Randomly try to start an anomaly."""
        if self.anomaly.active:
            return
        if random.random() > ANOMALY_PROBABILITY:
            return

        # Pick a scenario
        scenario = random.choice([
            "door_left_open",        # sudden temperature rise
            "cooler_failure",        # temperature drifts up
            "humidity_leak",         # humidity spikes
            "heater_failure",        # temperature drops
        ])
        duration = random.uniform(ANOMALY_DURATION_MIN, ANOMALY_DURATION_MAX)

        if scenario == "door_left_open":
            temp_off, hum_off = random.uniform(6, 10), random.uniform(5, 12)
        elif scenario == "cooler_failure":
            temp_off, hum_off = random.uniform(4, 7), 0.0
        elif scenario == "humidity_leak":
            temp_off, hum_off = 0.0, random.uniform(15, 25)
        else:  # heater_failure
            temp_off, hum_off = -random.uniform(5, 9), 0.0

        self.anomaly = AnomalyState(
            active=True,
            ends_at=time.time() + duration,
            scenario=scenario,
            temp_offset=temp_off,
            humidity_offset=hum_off,
        )
        print(
            f"[ANOMALY] {self.cfg['name']}: {scenario} "
            f"(duration ~{int(duration)}s, dT={temp_off:+.1f}, dH={hum_off:+.1f})"
        )

    def _tick_anomaly(self) -> None:
        """Ends the anomaly once its duration elapses."""
        if self.anomaly.active and time.time() >= self.anomaly.ends_at:
            print(f"[ANOMALY-END] {self.cfg['name']}: {self.anomaly.scenario}")
            self.anomaly = AnomalyState()

    def read(self) -> dict:
        """Produce one sensor reading."""
        self._maybe_trigger_anomaly()
        self._tick_anomaly()

        temp = self._diurnal(self.cfg["temp_center"], self.cfg["temp_amplitude"])
        temp += random.gauss(0, 0.3)  # sensor noise

        hum = self._diurnal(self.cfg["humidity_center"], self.cfg["humidity_amplitude"])
        hum += random.gauss(0, 0.8)

        if self.anomaly.active:
            temp += self.anomaly.temp_offset
            hum += self.anomaly.humidity_offset

        return {
            "warehouse_id": self.warehouse_id,
            "temperature": round(temp, 2),
            "humidity": round(max(0.0, min(100.0, hum)), 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "anomaly": self.anomaly.scenario if self.anomaly.active else None,
        }


class Publisher:
    """Thin wrapper around the MQTT client for publishing."""

    def __init__(self, host: str, port: int):
        # No callbacks are registered here - the simulator only publishes -
        # but the API version still has to be declared under paho 2.x.
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"simulator-{random.randint(1000, 9999)}",
        )
        self.host = host
        self.port = port
        self._connected = False

    def connect(self) -> None:
        # Broker may lag on startup (docker-compose), so retry
        for attempt in range(1, 11):
            try:
                self.client.connect(self.host, self.port, keepalive=30)
                self.client.loop_start()
                self._connected = True
                print(f"[MQTT] Connected to {self.host}:{self.port}.")
                return
            except Exception as e:  # broker may not be ready yet
                print(f"[MQTT] Connect attempt {attempt}/10 failed: {e}")
                time.sleep(2)
        raise RuntimeError("Could not connect to MQTT broker.")

    def publish(self, warehouse_id: str, reading: dict) -> None:
        # Temperature and humidity go on separate topics (as required)
        payload_temp = {
            "value": reading["temperature"],
            "unit": "C",
            "timestamp": reading["timestamp"],
            "anomaly": reading["anomaly"],
        }
        payload_hum = {
            "value": reading["humidity"],
            "unit": "%",
            "timestamp": reading["timestamp"],
            "anomaly": reading["anomaly"],
        }
        self.client.publish(f"warehouse/{warehouse_id}/temperature", json.dumps(payload_temp), qos=0)
        self.client.publish(f"warehouse/{warehouse_id}/humidity", json.dumps(payload_hum), qos=0)

    def close(self) -> None:
        if self._connected:
            self.client.loop_stop()
            self.client.disconnect()


_stop = threading.Event()


def _graceful_exit(signum, frame):
    print("\n[SIM] Shutting down...")
    _stop.set()


def sensor_loop(sensor: WarehouseSensor, publisher: Publisher) -> None:
    """Read-and-publish loop for a single warehouse."""
    while not _stop.is_set():
        reading = sensor.read()
        publisher.publish(sensor.warehouse_id, reading)
        flag = "!" if reading["anomaly"] else " "
        print(
            f" {flag} {sensor.cfg['name']:<20} "
            f"T={reading['temperature']:>5.2f}C  H={reading['humidity']:>5.2f}%"
        )
        # Each sensor picks its own random interval so they don't publish in lockstep
        time.sleep(random.uniform(PUBLISH_INTERVAL_MIN, PUBLISH_INTERVAL_MAX))


def main() -> int:
    signal.signal(signal.SIGINT, _graceful_exit)
    signal.signal(signal.SIGTERM, _graceful_exit)

    publisher = Publisher(MQTT_HOST, MQTT_PORT)
    publisher.connect()

    threads = []
    for warehouse_id, cfg in WAREHOUSES.items():
        sensor = WarehouseSensor(warehouse_id=warehouse_id, cfg=cfg)
        t = threading.Thread(target=sensor_loop, args=(sensor, publisher), daemon=True)
        t.start()
        threads.append(t)

    print(f"[SIM] Simulating {len(threads)} warehouses. Ctrl+C to stop.")
    try:
        while not _stop.is_set():
            time.sleep(1)
    finally:
        publisher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
