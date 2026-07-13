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

from collections import defaultdict, deque
from math import sqrt
from typing import Deque, Dict, List, Optional, Tuple

from .config import WAREHOUSE_THRESHOLDS, ZSCORE_THRESHOLD, ZSCORE_WINDOW


class AnomalyDetector:
    """Holds a sliding window per (warehouse, metric)."""

    def __init__(self) -> None:
        self._windows: Dict[Tuple[str, str], Deque[float]] = defaultdict(
            lambda: deque(maxlen=ZSCORE_WINDOW)
        )

    def _zscore_alert(self, warehouse_id: str, metric: str, value: float) -> Optional[str]:
        window = self._windows[(warehouse_id, metric)]
        # Wait until the window has enough samples - z-score is noisy otherwise
        if len(window) >= 10:
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            std = sqrt(var)
            if std > 0:
                z = (value - mean) / std
                if abs(z) > ZSCORE_THRESHOLD:
                    return (
                        f"Z-score deviation: {metric}={value:.2f} "
                        f"(mean={mean:.2f}, std={std:.2f}, z={z:.2f})"
                    )
        window.append(value)
        return None

    def _threshold_alert(self, warehouse_id: str, metric: str, value: float) -> Optional[str]:
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

    def evaluate(self, warehouse_id: str, metric: str, value: float) -> List[Tuple[str, str]]:
        """
        Returns all alerts for a single reading as [(alert_type, message), ...].
        """
        alerts: List[Tuple[str, str]] = []
        threshold = self._threshold_alert(warehouse_id, metric, value)
        if threshold:
            alerts.append(("threshold", threshold))
        z = self._zscore_alert(warehouse_id, metric, value)
        if z:
            alerts.append(("zscore", z))
        return alerts
