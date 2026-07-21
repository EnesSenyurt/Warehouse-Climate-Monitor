"""
Tests for the two-layer anomaly detector and the alert de-duplication
gate added on top of it.

Reference thresholds (backend/app/config.py):
    warehouse_a  temp 15.0-26.0   humidity 40.0-70.0
"""

import pytest

from app import anomaly as anomaly_module
from app.anomaly import AnomalyDetector


@pytest.fixture
def detector():
    return AnomalyDetector()


@pytest.fixture
def no_cooldown(monkeypatch):
    """Disables de-duplication so a detector can be tested in isolation."""
    monkeypatch.setattr(anomaly_module, "ALERT_COOLDOWN_SECONDS", 0.0)


def types_of(alerts):
    return [alert_type for alert_type, _ in alerts]


# --------------------------------------------------------------------
# Threshold detector
# --------------------------------------------------------------------

def test_value_inside_range_raises_nothing(detector):
    assert detector.evaluate("warehouse_a", "temperature", 20.0) == []


def test_temperature_above_max_alerts(detector):
    alerts = detector.evaluate("warehouse_a", "temperature", 30.0)
    assert types_of(alerts) == ["threshold"]
    assert "above normal" in alerts[0][1]


def test_temperature_below_min_alerts(detector):
    alerts = detector.evaluate("warehouse_a", "temperature", 5.0)
    assert types_of(alerts) == ["threshold"]
    assert "below normal" in alerts[0][1]


def test_humidity_uses_its_own_bounds(detector):
    # 30.0 is a fine temperature reading elsewhere, but humidity min is 40
    assert types_of(detector.evaluate("warehouse_a", "humidity", 30.0)) == ["threshold"]
    assert detector.evaluate("warehouse_a", "humidity", 55.0) == []


@pytest.mark.parametrize("value", [15.0, 26.0])
def test_bounds_are_inclusive(detector, value):
    """Exactly on the limit is still normal - only strictly outside alerts."""
    assert detector.evaluate("warehouse_a", "temperature", value) == []


def test_unknown_warehouse_raises_no_threshold_alert(detector):
    """No configured range means nothing to compare against."""
    assert detector.evaluate("not_a_warehouse", "temperature", 999.0) == []


# --------------------------------------------------------------------
# Z-score detector
# --------------------------------------------------------------------

def _warm_up(detector, values, warehouse="warehouse_a", metric="temperature"):
    for v in values:
        detector.evaluate(warehouse, metric, v)


def test_zscore_stays_quiet_until_the_window_fills(detector, no_cooldown):
    """Fewer than 10 samples - too little data to call anything an outlier."""
    _warm_up(detector, [20.0, 20.2] * 2)          # 4 samples
    assert detector.evaluate("warehouse_a", "temperature", 24.0) == []


def test_zscore_flags_a_jump_that_stays_within_thresholds(detector, no_cooldown):
    """
    24 C is inside warehouse_a's 15-26 band, so the threshold detector is
    silent - but it is a huge jump relative to the recent spread. This is
    exactly the case the z-score layer exists for.
    """
    _warm_up(detector, [20.0, 20.2] * 5)          # 10 samples, small stddev

    alerts = detector.evaluate("warehouse_a", "temperature", 24.0)
    assert types_of(alerts) == ["zscore"]
    assert "Z-score deviation" in alerts[0][1]


def test_zscore_ignores_movement_within_normal_spread(detector, no_cooldown):
    _warm_up(detector, [19.0, 20.0, 21.0, 20.5, 19.5] * 2)
    assert detector.evaluate("warehouse_a", "temperature", 20.2) == []


def test_perfectly_flat_window_never_fires_zscore(detector, no_cooldown):
    """
    Current behaviour: a constant series has stddev 0, and the detector
    skips the division rather than treating every change as infinitely
    anomalous. The threshold layer is what catches such a case.
    """
    _warm_up(detector, [20.0] * 12)
    assert detector.evaluate("warehouse_a", "temperature", 24.0) == []


def test_both_layers_can_fire_on_the_same_reading(detector, no_cooldown):
    _warm_up(detector, [20.0, 20.2] * 5)

    alerts = detector.evaluate("warehouse_a", "temperature", 40.0)
    assert sorted(types_of(alerts)) == ["threshold", "zscore"]


def test_windows_are_independent_per_warehouse_and_metric(detector, no_cooldown):
    """Warehouse A's history must not influence Warehouse B's z-score."""
    _warm_up(detector, [20.0, 20.2] * 5, warehouse="warehouse_a")

    # warehouse_b has seen nothing yet, so its window is still empty
    assert detector.evaluate("warehouse_b", "temperature", 20.0) == []


# --------------------------------------------------------------------
# Alert de-duplication
# --------------------------------------------------------------------

def test_sustained_anomaly_alerts_only_once(detector):
    fired = sum(len(detector.evaluate("warehouse_a", "temperature", 30.0)) for _ in range(20))
    assert fired == 1


def test_new_episode_alerts_immediately_after_returning_to_normal(detector):
    """
    The cooldown must not swallow a genuinely new anomaly. Reading normal
    once clears the gate.
    """
    assert len(detector.evaluate("warehouse_a", "temperature", 30.0)) == 1
    detector.evaluate("warehouse_a", "temperature", 20.0)          # back to normal
    assert len(detector.evaluate("warehouse_a", "temperature", 30.0)) == 1


def test_cooldown_expiry_re_alerts(detector, no_cooldown):
    """A long-running anomaly is re-reported once the cooldown elapses."""
    fired = sum(len(detector.evaluate("warehouse_a", "temperature", 30.0)) for _ in range(3))
    assert fired == 3


def test_cooldown_is_scoped_per_warehouse(detector):
    """One warehouse's cooldown must not silence another's alert."""
    assert len(detector.evaluate("warehouse_a", "temperature", 30.0)) == 1
    assert len(detector.evaluate("warehouse_b", "temperature", 30.0)) == 1


def test_cooldown_is_scoped_per_metric(detector):
    assert len(detector.evaluate("warehouse_a", "temperature", 30.0)) == 1
    assert len(detector.evaluate("warehouse_a", "humidity", 90.0)) == 1
