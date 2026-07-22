"""
Tests for the retention policy: the cutoff calculation, the delete itself
and the background loop that drives it.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app import main as main_module

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


# --------------------------------------------------------------------
# Cutoff calculation
# --------------------------------------------------------------------

def test_cutoff_is_retention_days_before_now(monkeypatch):
    monkeypatch.setattr(main_module, "RETENTION_DAYS", 7.0)

    assert main_module.retention_cutoff(NOW) == iso(NOW - timedelta(days=7))


def test_cutoff_honours_a_fractional_window(monkeypatch):
    monkeypatch.setattr(main_module, "RETENTION_DAYS", 0.5)

    assert main_module.retention_cutoff(NOW) == iso(NOW - timedelta(hours=12))


@pytest.mark.parametrize("days", [0.0, -1.0])
def test_retention_can_be_switched_off(monkeypatch, days):
    """0 or less means keep everything - the loop must never delete."""
    monkeypatch.setattr(main_module, "RETENTION_DAYS", days)

    assert main_module.retention_cutoff(NOW) is None


# --------------------------------------------------------------------
# The delete
# --------------------------------------------------------------------

def test_prune_deletes_only_rows_older_than_the_cutoff(db):
    old = iso(NOW - timedelta(days=10))
    recent = iso(NOW - timedelta(days=1))
    db.upsert_last_reading("warehouse_a", old, temperature=21.0, humidity=None)
    db.upsert_last_reading("warehouse_a", recent, temperature=22.0, humidity=None)

    db.prune_older_than(iso(NOW - timedelta(days=7)))

    remaining = db.history("warehouse_a", iso(NOW - timedelta(days=365)))
    assert [r["temperature"] for r in remaining] == [22.0]


def test_prune_deletes_aged_out_alerts_too(db):
    old = iso(NOW - timedelta(days=10))
    recent = iso(NOW - timedelta(days=1))
    db.insert_alert("warehouse_a", old, "threshold", "temperature", 30.0, "old")
    db.insert_alert("warehouse_a", recent, "threshold", "temperature", 31.0, "recent")

    db.prune_older_than(iso(NOW - timedelta(days=7)))

    assert [a["message"] for a in db.recent_alerts()] == ["recent"]


def test_prune_reports_how_much_it_removed(db):
    old = iso(NOW - timedelta(days=10))
    for _ in range(3):
        db.upsert_last_reading("warehouse_a", old, temperature=21.0, humidity=55.0)
    db.insert_alert("warehouse_a", old, "threshold", "temperature", 30.0, "old")

    removed = db.prune_older_than(iso(NOW - timedelta(days=7)))

    assert removed == {"readings": 3, "alerts": 1}


def test_prune_on_an_empty_database_is_a_no_op(db):
    assert db.prune_older_than(iso(NOW)) == {"readings": 0, "alerts": 0}


def test_prune_keeps_everything_when_nothing_is_old_enough(db):
    recent = iso(NOW - timedelta(hours=1))
    db.upsert_last_reading("warehouse_a", recent, temperature=21.0, humidity=None)

    assert db.prune_older_than(iso(NOW - timedelta(days=7)))["readings"] == 0
    assert len(db.latest_per_warehouse()) == 1


# --------------------------------------------------------------------
# The background loop
# --------------------------------------------------------------------

def test_prune_loop_runs_immediately_then_waits(db, monkeypatch):
    """
    The loop must prune on startup rather than after the first full
    interval, otherwise a short-lived process never prunes at all.
    """
    monkeypatch.setattr(main_module, "RETENTION_DAYS", 7.0)
    monkeypatch.setattr(main_module, "PRUNE_INTERVAL_SECONDS", 3600)

    old = iso(datetime.now(timezone.utc) - timedelta(days=10))
    db.upsert_last_reading("warehouse_a", old, temperature=21.0, humidity=None)

    async def run_one_pass():
        task = asyncio.create_task(main_module.prune_loop())
        # The delete runs in a worker thread, so give it real time to land
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not db.latest_per_warehouse():
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_one_pass())
    assert db.latest_per_warehouse() == []


def test_prune_loop_survives_a_failing_prune(db, monkeypatch):
    """One bad tick must not silently end retention for the process."""
    monkeypatch.setattr(main_module, "RETENTION_DAYS", 7.0)
    monkeypatch.setattr(main_module, "PRUNE_INTERVAL_SECONDS", 0)

    calls = []

    def exploding_prune(cutoff):
        calls.append(cutoff)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return {"readings": 0, "alerts": 0}

    monkeypatch.setattr(main_module.db, "prune_older_than", exploding_prune)

    async def run_a_few_passes():
        task = asyncio.create_task(main_module.prune_loop())
        for _ in range(100):
            await asyncio.sleep(0.01)
            if len(calls) >= 2:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_a_few_passes())
    assert len(calls) >= 2, "loop stopped after the first failure"
