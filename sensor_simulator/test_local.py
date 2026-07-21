"""
Quick smoke test that validates the sensor logic without an MQTT broker.
Runs a few reading cycles and checks values are within a sane range.

Usage:
    python test_local.py
"""

import warnings

from config import WAREHOUSES
from simulator import Publisher, WarehouseSensor


def check_mqtt_client_setup() -> None:
    """
    Building a Publisher creates the paho client but does not connect.
    paho 2.x still accepts the old callback API through a shim that warns,
    so treat that warning as a failure.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        Publisher("localhost", 1883)


def main() -> None:
    check_mqtt_client_setup()

    for warehouse_id, cfg in WAREHOUSES.items():
        sensor = WarehouseSensor(warehouse_id=warehouse_id, cfg=cfg)
        readings = [sensor.read() for _ in range(5)]
        temps = [r["temperature"] for r in readings]
        hums = [r["humidity"] for r in readings]
        print(
            f"{cfg['name']:<20} "
            f"T[{min(temps):.2f}..{max(temps):.2f}]C  "
            f"H[{min(hums):.2f}..{max(hums):.2f}]%"
        )
        # Basic sanity - values should be near the configured range
        assert all(-10 < t < 60 for t in temps), "temperature out of sane range"
        assert all(0 <= h <= 100 for h in hums), "humidity outside 0-100"

    print("OK - sensor logic works.")


if __name__ == "__main__":
    main()
