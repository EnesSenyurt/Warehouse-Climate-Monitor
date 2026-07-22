"""
MQTT subscriber. For every incoming message it:
  - Persists the reading to the database
  - Runs the anomaly detector
  - Broadcasts the reading (and any alerts) over WebSocket to the dashboard

paho-mqtt runs its callback on its own thread while FastAPI/WebSocket runs
on an asyncio event loop. `asyncio.run_coroutine_threadsafe` is used to
cross that boundary.
"""

import asyncio
import json
import time
from math import isfinite

import paho.mqtt.client as mqtt

from . import db
from .anomaly import AnomalyDetector
from .config import MQTT_HOST, MQTT_PORT, WAREHOUSE_THRESHOLDS


class MQTTBridge:
    def __init__(self, ws_manager, loop: asyncio.AbstractEventLoop) -> None:
        self.ws_manager = ws_manager
        self.loop = loop
        self.detector = AnomalyDetector()
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="backend-subscriber"
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        # Subscriptions are (re)made here so they survive an automatic
        # reconnect - paho does not replay them for us.
        print(f"[MQTT] connect: {reason_code}")
        client.subscribe("warehouse/+/temperature")
        client.subscribe("warehouse/+/humidity")

    def _parse_topic(self, topic: str) -> tuple | None:
        # warehouse/{id}/temperature  or  warehouse/{id}/humidity
        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "warehouse":
            return None
        return parts[1], parts[2]

    def _on_message(self, client, userdata, msg):
        parsed = self._parse_topic(msg.topic)
        if not parsed:
            return
        warehouse_id, metric = parsed

        # An unconfigured warehouse has no thresholds, so nothing would
        # check its readings, and /current only lists configured ones -
        # the rows would pile up unseen. Drop them loudly instead: the log
        # line is how a device publishing under a typo'd id gets noticed.
        if warehouse_id not in WAREHOUSE_THRESHOLDS:
            print(f"[MQTT] unknown warehouse '{warehouse_id}', dropped "
                  f"(add it to WAREHOUSE_THRESHOLDS to start recording it)")
            return

        # Defensive: the subscriptions only cover these two metrics, but
        # the threshold lookup would otherwise fall back to the humidity
        # bounds for anything unrecognised.
        if metric not in ("temperature", "humidity"):
            print(f"[MQTT] unknown metric '{metric}', dropped")
            return

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            print(f"[MQTT] payload parse error: {e}")
            return

        # Anything can publish to these topics, so treat the payload as
        # untrusted: a bad message must be dropped, not kill the callback.
        if not isinstance(payload, dict):
            print(f"[MQTT] {msg.topic}: payload is not a JSON object, dropped")
            return

        try:
            value = float(payload["value"])
        except (KeyError, TypeError, ValueError):
            print(f"[MQTT] {msg.topic}: missing or non-numeric 'value', dropped")
            return

        # NaN/inf would permanently poison the z-score window's mean and stddev
        if not isfinite(value):
            print(f"[MQTT] {msg.topic}: non-finite 'value', dropped")
            return

        timestamp = payload.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp:
            print(f"[MQTT] {msg.topic}: missing or invalid 'timestamp', dropped")
            return

        # Persist - since temperature and humidity come on separate topics, merge them
        if metric == "temperature":
            db.upsert_last_reading(warehouse_id, timestamp, temperature=value, humidity=None)
        else:
            db.upsert_last_reading(warehouse_id, timestamp, temperature=None, humidity=value)

        # Anomaly detection
        alerts = self.detector.evaluate(warehouse_id, metric, value)
        alert_records = []
        for alert_type, message in alerts:
            record = db.insert_alert(warehouse_id, timestamp, alert_type, metric, value, message)
            alert_records.append(record)
            print(f"[ALERT] {warehouse_id} {metric}={value:.2f} :: {message}")

        # Broadcast - hop from mqtt thread to asyncio loop
        broadcast_msg = {
            "type": "reading",
            "warehouse_id": warehouse_id,
            "metric": metric,
            "value": value,
            "timestamp": timestamp,
            "alerts": alert_records,
        }
        asyncio.run_coroutine_threadsafe(
            self.ws_manager.broadcast(broadcast_msg), self.loop
        )

    def start(self) -> None:
        # Broker may lag on startup - retry
        for attempt in range(1, 21):
            try:
                self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
                self.client.loop_start()
                print(f"[MQTT] Connected to {MQTT_HOST}:{MQTT_PORT}.")
                return
            except Exception as e:
                print(f"[MQTT] Attempt {attempt}/20 failed: {e}")
                time.sleep(2)
        print("[MQTT] Could not connect - subscriber offline.")

    def stop(self) -> None:
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
