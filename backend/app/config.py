"""Backend configuration. Warehouse thresholds must match the simulator."""

import os

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DB_PATH = os.getenv("DB_PATH", "data/warehouse.db")

# Per-warehouse thresholds used by the threshold-based anomaly detector.
# Kept in sync with the simulator config by hand for now; in a real
# project this would come from a shared source of truth.
WAREHOUSE_THRESHOLDS = {
    "warehouse_a":        {"name": "Warehouse A",        "temp_min": 15.0, "temp_max": 26.0, "hum_min": 40.0, "hum_max": 70.0},
    "warehouse_b":        {"name": "Warehouse B",        "temp_min": 12.0, "temp_max": 24.0, "hum_min": 45.0, "hum_max": 75.0},
    "paint_workshop":     {"name": "Paint Workshop",     "temp_min": 18.0, "temp_max": 30.0, "hum_min": 30.0, "hum_max": 60.0},
    "electrical_storage": {"name": "Electrical Storage", "temp_min": 10.0, "temp_max": 25.0, "hum_min": 25.0, "hum_max": 55.0},
}

# Z-score anomaly detector - window size and deviation threshold.
ZSCORE_WINDOW = 30       # last N samples
ZSCORE_THRESHOLD = 3.0   # |z| > 3 counts as a deviation
