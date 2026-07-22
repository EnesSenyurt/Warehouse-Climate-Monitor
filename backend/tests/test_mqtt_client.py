"""
Tests for the MQTT message handler.

The bridge is built with `__new__` so no paho client is created and no
broker connection is attempted - `_on_message` only needs the detector,
the db module and a broadcast target.
"""

import asyncio
import json
import threading
import types
import warnings

import pytest

from app.anomaly import AnomalyDetector
from app.mqtt_client import MQTTBridge

TS = "2026-07-21T10:00:00+00:00"


class RecordingWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)


@pytest.fixture
def loop():
    """A real event loop on a background thread, for run_coroutine_threadsafe."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)


@pytest.fixture
def bridge(db, loop):
    b = MQTTBridge.__new__(MQTTBridge)
    b.ws_manager = RecordingWS()
    b.detector = AnomalyDetector()
    b.loop = loop
    return b


def deliver(bridge, payload, topic="warehouse/warehouse_a/temperature"):
    """Feeds a raw payload through the handler as paho would."""
    raw = payload if isinstance(payload, bytes | str) else json.dumps(payload)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    bridge._on_message(None, None, types.SimpleNamespace(topic=topic, payload=raw))


def settle(bridge, timeout=2.0):
    """Waits for queued broadcasts to run on the background loop."""
    done = threading.Event()
    bridge.loop.call_soon_threadsafe(done.set)
    done.wait(timeout)
    return bridge.ws_manager.messages


# --------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------

def test_valid_reading_is_stored_and_broadcast(bridge, db):
    deliver(bridge, {"value": 21.5, "unit": "C", "timestamp": TS})

    stored = db.latest_per_warehouse()
    assert len(stored) == 1
    assert stored[0]["temperature"] == 21.5

    (message,) = settle(bridge)
    assert message["type"] == "reading"
    assert message["metric"] == "temperature"
    assert message["value"] == 21.5


def test_temperature_and_humidity_merge_into_one_row(bridge, db):
    deliver(bridge, {"value": 21.5, "timestamp": TS})
    deliver(bridge, {"value": 55.0, "timestamp": TS}, topic="warehouse/warehouse_a/humidity")

    (row,) = db.latest_per_warehouse()
    assert (row["temperature"], row["humidity"]) == (21.5, 55.0)
    assert len(settle(bridge)) == 2


def test_out_of_range_reading_stores_an_alert(bridge, db):
    deliver(bridge, {"value": 35.0, "timestamp": TS})

    (alert,) = db.recent_alerts()
    assert alert["alert_type"] == "threshold"
    assert alert["metric"] == "temperature"

    (message,) = settle(bridge)
    assert len(message["alerts"]) == 1


def test_sustained_anomaly_is_not_written_on_every_reading(bridge, db):
    """End-to-end check that de-duplication reaches the database."""
    for _ in range(10):
        deliver(bridge, {"value": 35.0, "timestamp": TS})

    assert len(db.recent_alerts()) == 1


# --------------------------------------------------------------------
# Malformed payloads - must be dropped, never raise
# --------------------------------------------------------------------

MALFORMED = {
    "not json": b"{oops",
    "not utf-8": b"\xff\xfe\x00",
    "json but not an object": b"[1, 2, 3]",
    "json scalar": b"42",
    "missing value": {"timestamp": TS},
    "value is a string": {"value": "warm", "timestamp": TS},
    "value is null": {"value": None, "timestamp": TS},
    "value is a list": {"value": [1], "timestamp": TS},
    "value is NaN": b'{"value": NaN, "timestamp": "2026-07-21T10:00:00+00:00"}',
    "value is Infinity": b'{"value": Infinity, "timestamp": "2026-07-21T10:00:00+00:00"}',
    "missing timestamp": {"value": 21.5},
    "timestamp is a number": {"value": 21.5, "timestamp": 123},
    "timestamp is empty": {"value": 21.5, "timestamp": ""},
}


@pytest.mark.parametrize("payload", MALFORMED.values(), ids=list(MALFORMED))
def test_malformed_payload_is_dropped_silently(bridge, db, payload):
    deliver(bridge, payload)          # must not raise

    assert db.latest_per_warehouse() == []
    assert db.recent_alerts() == []
    assert settle(bridge) == []


def test_nan_does_not_poison_the_zscore_window(bridge, db):
    """
    A NaN reaching the rolling window would make its mean and stddev NaN
    permanently, silently disabling the z-score detector for that series.
    """
    deliver(bridge, b'{"value": NaN, "timestamp": "2026-07-21T10:00:00+00:00"}')
    for value in [20.0, 20.2] * 5:
        deliver(bridge, {"value": value, "timestamp": TS})

    alerts = bridge.detector.evaluate("warehouse_a", "temperature", 24.0)
    assert [t for t, _ in alerts] == ["zscore"]


# --------------------------------------------------------------------
# Client setup
#
# Constructing MQTTBridge only builds the paho client and wires the
# callbacks - no connection is attempted until start() is called.
# --------------------------------------------------------------------

def test_client_uses_a_non_deprecated_callback_api(loop):
    """paho 2.x still accepts the v1 API, but warns. Fail on that warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        MQTTBridge(RecordingWS(), loop)


def test_on_connect_subscribes_to_both_metric_topics(loop):
    bridge = MQTTBridge(RecordingWS(), loop)
    subscribed = []
    client = types.SimpleNamespace(subscribe=subscribed.append)

    bridge._on_connect(client, None, {}, 0)

    assert subscribed == ["warehouse/+/temperature", "warehouse/+/humidity"]


# --------------------------------------------------------------------
# Topic routing
# --------------------------------------------------------------------

@pytest.mark.parametrize("topic", [
    "warehouse/warehouse_a",              # too few segments
    "warehouse/warehouse_a/temp/extra",   # too many
    "other/warehouse_a/temperature",      # wrong prefix
])
def test_unrecognised_topic_is_ignored(bridge, db, topic):
    deliver(bridge, {"value": 21.5, "timestamp": TS}, topic=topic)

    assert db.latest_per_warehouse() == []
    assert settle(bridge) == []


def test_unknown_warehouse_is_dropped(bridge, db):
    """
    Nothing would range-check these readings and /current would never show
    them, so storing them just grows the table with invisible rows.
    """
    deliver(bridge, {"value": 21.5, "timestamp": TS},
            topic="warehouse/typo_warehouse/temperature")

    assert db.latest_per_warehouse() == []
    assert settle(bridge) == []


def test_unknown_metric_is_dropped(bridge, db):
    """Guards the threshold lookup, which treats any non-temperature
    metric as humidity."""
    deliver(bridge, {"value": 1013.0, "timestamp": TS},
            topic="warehouse/warehouse_a/pressure")

    assert db.latest_per_warehouse() == []
    assert settle(bridge) == []


def test_every_configured_warehouse_is_accepted(bridge, db):
    """Complements the drop tests - the allowlist must not be too narrow."""
    from app.config import WAREHOUSE_THRESHOLDS

    for warehouse_id in WAREHOUSE_THRESHOLDS:
        deliver(bridge, {"value": 20.0, "timestamp": TS},
                topic=f"warehouse/{warehouse_id}/temperature")

    stored = {row["warehouse_id"] for row in db.latest_per_warehouse()}
    assert stored == set(WAREHOUSE_THRESHOLDS)
