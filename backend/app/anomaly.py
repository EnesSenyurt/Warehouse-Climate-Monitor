"""
Two-layer anomaly detection:

1) Threshold-based: each warehouse has a [min, max] normal range.
   Values outside that range raise an alarm. Simple but strict:
   "Warehouse A > 26 C" -> alert.

2) Z-score based: computes mean and standard deviation over the last
   N samples and flags |z| > threshold as a statistical outlier.
   Catches sudden jumps even if they stay inside the threshold band.

The two layers run independently; either can raise an alert.
"""

import time
from collections import defaultdict, deque
from math import sqrt

from .config import (
    ALERT_COOLDOWN_SECONDS,
    WAREHOUSE_THRESHOLDS,
    ZSCORE_MIN_SAMPLES,
    ZSCORE_THRESHOLD,
    ZSCORE_WINDOW,
)

ALERT_TYPES = ("threshold", "zscore")


class AnomalyDetector:
    """Holds a sliding window per (warehouse, metric)."""

    def __init__(self) -> None:
        self._windows: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=ZSCORE_WINDOW)
        )
        # (warehouse, metric, alert_type) -> monotonic time the last alert was emitted
        self._last_alert_at: dict[tuple[str, str, str], float] = {}

    def _zscore_alert(self, warehouse_id: str, metric: str, value: float) -> str | None:
        window = self._windows[(warehouse_id, metric)]
        alert: str | None = None

        # Wait until the window has enough samples - z-score is noisy otherwise
        if len(window) >= ZSCORE_MIN_SAMPLES:
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            std = sqrt(var)
            if std > 0:
                z = (value - mean) / std
                if abs(z) > ZSCORE_THRESHOLD:
                    alert = (
                        f"Z-score deviation: {metric}={value:.2f} "
                        f"(mean={mean:.2f}, std={std:.2f}, z={z:.2f})"
                    )

        # The sample joins the window whether or not it alerted, so the
        # baseline keeps tracking reality. A sustained shift therefore
        # becomes the new normal after roughly ZSCORE_WINDOW samples and
        # this detector goes quiet - by design. Staying outside the
        # configured range is the threshold detector's job to report, and
        # it keeps firing for as long as the condition lasts.
        window.append(value)
        return alert

    def _threshold_alert(self, warehouse_id: str, metric: str, value: float) -> str | None:
        cfg = WAREHOUSE_THRESHOLDS.get(warehouse_id)
        if not cfg:
            return None
        if metric == "temperature":
            lo, hi = cfg["temp_min"], cfg["temp_max"]
        else:
            lo, hi = cfg["hum_min"], cfg["hum_max"]

        if value < lo:
            return f"{metric} below normal: {value:.2f} < {lo:.2f}"
        if value > hi:
            return f"{metric} above normal: {value:.2f} > {hi:.2f}"
        return None

    def evaluate(self, warehouse_id: str, metric: str, value: float) -> list[tuple[str, str]]:
        """
        Returns the alerts worth recording for a single reading, as
        [(alert_type, message), ...].

        Both detectors run on every reading, but a sustained anomaly is
        reported at most once per ALERT_COOLDOWN_SECONDS - see _dedupe.
        """
        fired: list[tuple[str, str]] = []
        threshold = self._threshold_alert(warehouse_id, metric, value)
        if threshold:
            fired.append(("threshold", threshold))
        z = self._zscore_alert(warehouse_id, metric, value)
        if z:
            fired.append(("zscore", z))
        return self._dedupe(warehouse_id, metric, fired)

    def _dedupe(
        self, warehouse_id: str, metric: str, fired: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """
        Suppresses repeat alerts while an anomaly persists.

        An alert type that did NOT fire this round has its cooldown cleared,
        so the next occurrence is reported immediately rather than being
        swallowed by a cooldown left over from an earlier episode.
        """
        now = time.monotonic()
        fired_types = {alert_type for alert_type, _ in fired}

        for alert_type in ALERT_TYPES:
            if alert_type not in fired_types:
                self._last_alert_at.pop((warehouse_id, metric, alert_type), None)

        kept: list[tuple[str, str]] = []
        for alert_type, message in fired:
            key = (warehouse_id, metric, alert_type)
            last = self._last_alert_at.get(key)
            if last is not None and now - last < ALERT_COOLDOWN_SECONDS:
                continue
            self._last_alert_at[key] = now
            kept.append((alert_type, message))
        return kept
