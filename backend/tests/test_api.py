"""
REST endpoint tests.

TestClient is deliberately NOT used as a context manager: that would run
the app's lifespan, which starts the MQTT bridge and blocks for ~40 s
retrying against a broker that isn't there. Plain request calls exercise
the routes without it; the `db` fixture handles schema setup instead.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import WAREHOUSE_THRESHOLDS
from app.main import app

TS = "2026-07-21T10:00:00+00:00"


@pytest.fixture
def client(db):
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_warehouses_lists_every_configured_warehouse(client):
    r = client.get("/warehouses")
    assert r.status_code == 200

    body = r.json()
    assert {w["id"] for w in body} == set(WAREHOUSE_THRESHOLDS)
    assert all({"name", "temp_min", "temp_max", "hum_min", "hum_max"} <= set(w) for w in body)


def test_current_lists_all_warehouses_even_with_no_data(client):
    """A warehouse that has never reported still appears, with null values."""
    body = client.get("/current").json()

    assert {w["warehouse_id"] for w in body} == set(WAREHOUSE_THRESHOLDS)
    assert all(w["temperature"] is None and w["timestamp"] is None for w in body)


def test_current_reports_the_latest_reading(client, db):
    db.upsert_last_reading("warehouse_a", TS, temperature=21.5, humidity=None)
    db.upsert_last_reading("warehouse_a", TS, temperature=None, humidity=55.0)

    body = client.get("/current").json()
    a = [w for w in body if w["warehouse_id"] == "warehouse_a"][0]

    assert (a["temperature"], a["humidity"]) == (21.5, 55.0)
    assert a["temp_max"] == WAREHOUSE_THRESHOLDS["warehouse_a"]["temp_max"]


def test_history_returns_recent_rows(client, db):
    db.upsert_last_reading("warehouse_a", TS, temperature=21.5, humidity=None)

    r = client.get("/history/warehouse_a", params={"hours": 168})
    assert r.status_code == 200
    assert [row["temperature"] for row in r.json()] == [21.5]


def test_history_excludes_readings_older_than_the_window(client, db):
    db.upsert_last_reading("warehouse_a", "2020-01-01T00:00:00+00:00", temperature=21.5, humidity=None)

    assert client.get("/history/warehouse_a", params={"hours": 1}).json() == []


def test_history_rejects_unknown_warehouse(client):
    r = client.get("/history/not_a_warehouse")
    assert r.status_code == 404


@pytest.mark.parametrize("hours", [0, 200, -1])
def test_history_rejects_out_of_range_windows(client, hours):
    """Guards against unbounded scans - hours is constrained to 0.05-168."""
    assert client.get("/history/warehouse_a", params={"hours": hours}).status_code == 422


def test_alerts_are_newest_first(client, db):
    for i in range(3):
        db.insert_alert("warehouse_a", TS, "threshold", "temperature", float(i), f"alert {i}")

    body = client.get("/alerts").json()
    assert [a["message"] for a in body] == ["alert 2", "alert 1", "alert 0"]


def test_alerts_respects_limit(client, db):
    for i in range(5):
        db.insert_alert("warehouse_a", TS, "threshold", "temperature", float(i), f"alert {i}")

    assert len(client.get("/alerts", params={"limit": 2}).json()) == 2


@pytest.mark.parametrize("limit", [0, 1001])
def test_alerts_rejects_out_of_range_limit(client, limit):
    assert client.get("/alerts", params={"limit": limit}).status_code == 422
