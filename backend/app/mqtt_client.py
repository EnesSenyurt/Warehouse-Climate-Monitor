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
from typing import Optional

import paho.mqtt.client as mqtt

from .anomaly import AnomalyDetector
from .config import MQTT_HOST, MQTT_PORT
from . import db


class MQTTBridge:
    def __init__(self, ws_manager, loop: asyncio.AbstractEventLoop) -> None:
        self.ws_manager = ws_manager
        self.loop = loop
        self.detector = AnomalyDetector()
        self.client = mqtt.Client(client_id="backend-subscriber")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] connect rc={rc}")
        client.subscribe("warehouse/+/temperature")
        client.subscribe("warehouse/+/humidity")

    def _parse_topic(self, topic: str) -> Optional[tuple]:
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
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            print(f"[MQTT] payload parse error: {e}")
            return

        value = float(payload["value"])
        timestamp = payload["timestamp"]

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
