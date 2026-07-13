"""
MQTT broker olmadan sensör mantığını doğrulayan hızlı test.
Bir kaç tur okuma yapar ve değerlerin makul aralıkta olduğunu kontrol eder.

Kullanım:
    python test_local.py
"""

from config import WAREHOUSES
from simulator import WarehouseSensor


def main() -> None:
    for depo_id, cfg in WAREHOUSES.items():
        sensor = WarehouseSensor(depo_id=depo_id, cfg=cfg)
        readings = [sensor.read() for _ in range(5)]
        temps = [r["sicaklik"] for r in readings]
        hums = [r["nem"] for r in readings]
        print(
            f"{cfg['name']:<18} "
            f"T[{min(temps):.2f}..{max(temps):.2f}]°C  "
            f"H[{min(hums):.2f}..{max(hums):.2f}]%"
        )
        # Basit sağlık kontrolü - normal aralığın makul yakınında olmalı
        assert all(-10 < t < 60 for t in temps), "Sıcaklık makul dışı"
        assert all(0 <= h <= 100 for h in hums), "Nem 0-100 dışı"

    print("OK - sensor logic works.")


if __name__ == "__main__":
    main()
