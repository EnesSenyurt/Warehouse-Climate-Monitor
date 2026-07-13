"""
Warehouse configuration.
Each virtual warehouse has its own normal temperature/humidity range,
so that "Paint Workshop" is naturally warmer, "Electrical Storage" is
drier, etc. — giving realistic per-warehouse behavior.
"""

WAREHOUSES = {
    "warehouse_a": {
        "name": "Warehouse A",
        "temp_center": 20.0,       # Mean temperature (C)
        "temp_amplitude": 2.5,     # Diurnal variation amplitude
        "temp_min": 15.0,          # Alarm threshold - lower bound
        "temp_max": 26.0,          # Alarm threshold - upper bound
        "humidity_center": 55.0,   # Mean humidity (%)
        "humidity_amplitude": 5.0,
        "humidity_min": 40.0,
        "humidity_max": 70.0,
    },
    "warehouse_b": {
        "name": "Warehouse B",
        "temp_center": 18.0,
        "temp_amplitude": 2.0,
        "temp_min": 12.0,
        "temp_max": 24.0,
        "humidity_center": 60.0,
        "humidity_amplitude": 6.0,
        "humidity_min": 45.0,
        "humidity_max": 75.0,
    },
    "paint_workshop": {
        "name": "Paint Workshop",
        "temp_center": 24.0,       # Paint likes it warmer
        "temp_amplitude": 3.0,
        "temp_min": 18.0,
        "temp_max": 30.0,
        "humidity_center": 45.0,   # Paint needs low humidity
        "humidity_amplitude": 4.0,
        "humidity_min": 30.0,
        "humidity_max": 60.0,
    },
    "electrical_storage": {
        "name": "Electrical Storage",
        "temp_center": 19.0,
        "temp_amplitude": 1.5,
        "temp_min": 10.0,
        "temp_max": 25.0,
        "humidity_center": 40.0,   # Electronics: keep humidity low
        "humidity_amplitude": 3.0,
        "humidity_min": 25.0,
        "humidity_max": 55.0,
    },
}

# MQTT settings - inside docker-compose the 'mosquitto' hostname is used;
# outside Docker it falls back to localhost.
import os

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# Publish interval - seconds
PUBLISH_INTERVAL_MIN = 5
PUBLISH_INTERVAL_MAX = 10

# Anomaly injection probability (per publish)
ANOMALY_PROBABILITY = 0.02   # 2% chance an anomaly starts
ANOMALY_DURATION_MIN = 30    # Seconds
ANOMALY_DURATION_MAX = 120
