"""
Tests for the SQLite layer, focused on `upsert_last_reading` - the
trickiest piece of logic in the project. Temperature and humidity arrive
as two separate MQTT messages, and this function decides whether to fold
the second one into the existing row or start a new one.
"""

TS1 = "2026-07-21T10:00:00+00:00"
TS2 = "2026-07-21T10:00:05+00:00"
TS3 = "2026-07-21T10:00:10+00:00"


def _rows(db):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM readings ORDER BY id").fetchall()]


def test_temperature_then_humidity_merges_into_one_row(db):
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.5, humidity=None)
    db.upsert_last_reading("warehouse_a", TS1, temperature=None, humidity=55.0)

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["temperature"] == 21.5
    assert rows[0]["humidity"] == 55.0


def test_humidity_then_temperature_also_merges(db):
    """Order must not matter - humidity can arrive first."""
    db.upsert_last_reading("warehouse_a", TS1, temperature=None, humidity=55.0)
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.5, humidity=None)

    rows = _rows(db)
    assert len(rows) == 1
    assert (rows[0]["temperature"], rows[0]["humidity"]) == (21.5, 55.0)


def test_two_temperatures_in_a_row_create_two_rows(db):
    """The counterpart column is already filled, so no merge is possible."""
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.5, humidity=None)
    db.upsert_last_reading("warehouse_a", TS2, temperature=22.0, humidity=None)

    rows = _rows(db)
    assert len(rows) == 2
    assert [r["temperature"] for r in rows] == [21.5, 22.0]
    assert [r["humidity"] for r in rows] == [None, None]


def test_full_pair_then_new_reading_starts_a_new_row(db):
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.5, humidity=None)
    db.upsert_last_reading("warehouse_a", TS1, temperature=None, humidity=55.0)
    db.upsert_last_reading("warehouse_a", TS2, temperature=22.0, humidity=None)

    rows = _rows(db)
    assert len(rows) == 2
    assert rows[1]["temperature"] == 22.0
    assert rows[1]["humidity"] is None


def test_merge_is_scoped_per_warehouse(db):
    """Warehouse B's humidity must not be folded into Warehouse A's row."""
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.5, humidity=None)
    db.upsert_last_reading("warehouse_b", TS1, temperature=None, humidity=60.0)

    rows = _rows(db)
    assert len(rows) == 2
    a = [r for r in rows if r["warehouse_id"] == "warehouse_a"][0]
    b = [r for r in rows if r["warehouse_id"] == "warehouse_b"][0]
    assert (a["temperature"], a["humidity"]) == (21.5, None)
    assert (b["temperature"], b["humidity"]) == (None, 60.0)


def test_merge_advances_the_timestamp(db):
    """The merged row carries the newer of the two timestamps."""
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.5, humidity=None)
    db.upsert_last_reading("warehouse_a", TS2, temperature=None, humidity=55.0)

    assert _rows(db)[0]["timestamp"] == TS2


def test_latest_per_warehouse_returns_newest_row_each(db):
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.5, humidity=None)
    db.upsert_last_reading("warehouse_a", TS2, temperature=22.0, humidity=None)
    db.upsert_last_reading("warehouse_b", TS1, temperature=18.0, humidity=None)

    latest = {r["warehouse_id"]: r for r in db.latest_per_warehouse()}
    assert set(latest) == {"warehouse_a", "warehouse_b"}
    assert latest["warehouse_a"]["temperature"] == 22.0
    assert latest["warehouse_b"]["temperature"] == 18.0


def test_latest_per_warehouse_is_empty_before_any_reading(db):
    assert db.latest_per_warehouse() == []


def test_history_filters_by_since_and_sorts_ascending(db):
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.0, humidity=None)
    db.upsert_last_reading("warehouse_a", TS2, temperature=22.0, humidity=None)
    db.upsert_last_reading("warehouse_a", TS3, temperature=23.0, humidity=None)

    rows = db.history("warehouse_a", TS2)
    assert [r["temperature"] for r in rows] == [22.0, 23.0]


def test_history_ignores_other_warehouses(db):
    db.upsert_last_reading("warehouse_a", TS1, temperature=21.0, humidity=None)
    db.upsert_last_reading("warehouse_b", TS1, temperature=18.0, humidity=None)

    rows = db.history("warehouse_a", TS1)
    assert len(rows) == 1
    assert rows[0]["warehouse_id"] == "warehouse_a"


def test_insert_alert_returns_the_stored_record(db):
    rec = db.insert_alert("warehouse_a", TS1, "threshold", "temperature", 30.0, "too hot")

    assert rec["id"] is not None
    assert rec["warehouse_id"] == "warehouse_a"
    assert rec["alert_type"] == "threshold"
    assert rec["value"] == 30.0
    assert rec["message"] == "too hot"


def test_recent_alerts_are_newest_first_and_respect_limit(db):
    for i in range(5):
        db.insert_alert("warehouse_a", TS1, "threshold", "temperature", float(i), f"alert {i}")

    recent = db.recent_alerts(limit=3)
    assert len(recent) == 3
    assert [r["message"] for r in recent] == ["alert 4", "alert 3", "alert 2"]
