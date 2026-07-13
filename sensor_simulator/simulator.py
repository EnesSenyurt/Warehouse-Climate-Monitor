"""
Sensör simülatörü.

Her depo için ayrı bir "sanal sensör" çalıştırır. Sensörler:
  - Sinüs fonksiyonu ile gün içi doğal dalgalanma üretir
  - Küçük rastgele gürültü ekler (gerçek sensör toleransı hissi)
  - Rastgele zamanlarda anomali senaryosu tetikler
    (örn. "kapı açık kaldı" -> sıcaklık hızlıca artar)
  - MQTT broker'a `depo/{depo_id}/sicaklik` ve
    `depo/{depo_id}/nem` topic'lerinde yayın yapar.

Bu dosya tek başına çalışabilir:
    python simulator.py
"""

import json
import math
import random
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt

from config import (
    ANOMALY_DURATION_MAX,
    ANOMALY_DURATION_MIN,
    ANOMALY_PROBABILITY,
    MQTT_HOST,
    MQTT_PORT,
    PUBLISH_INTERVAL_MAX,
    PUBLISH_INTERVAL_MIN,
    WAREHOUSES,
)


@dataclass
class AnomalyState:
    """Depoda o an aktif olan anomali (varsa)."""
    active: bool = False
    ends_at: float = 0.0
    scenario: str = ""
    temp_offset: float = 0.0
    humidity_offset: float = 0.0


@dataclass
class WarehouseSensor:
    """Tek bir depo için sanal sensör."""
    depo_id: str
    cfg: dict
    anomaly: AnomalyState = field(default_factory=AnomalyState)
    started_at: float = field(default_factory=time.time)

    def _diurnal(self, center: float, amplitude: float) -> float:
        """
        Gün içi sinüs dalgası. 24 saatlik periyot ile modellenmiş,
        ancak simülasyonu hızlı görebilmek için 10 dakikaya sıkıştırdım.
        Böylece sunum sırasında bir "gün döngüsü" birkaç dakikada gözlenebilir.
        """
        period_seconds = 600  # 10 dk = 1 gün simülasyonu
        elapsed = time.time() - self.started_at
        phase = (elapsed % period_seconds) / period_seconds * 2 * math.pi
        return center + amplitude * math.sin(phase)

    def _maybe_trigger_anomaly(self) -> None:
        """Rastgele bir anomali başlatma denemesi."""
        if self.anomaly.active:
            return
        if random.random() > ANOMALY_PROBABILITY:
            return

        # Senaryo seç
        scenario = random.choice([
            "kapi_acik_kaldi",       # sıcaklık aniden artar
            "sogutucu_arizasi",      # sıcaklık yavaş yavaş yükselir
            "nem_sizinti",           # nem aniden yükselir
            "isitici_arizasi",       # sıcaklık düşer
        ])
        duration = random.uniform(ANOMALY_DURATION_MIN, ANOMALY_DURATION_MAX)

        if scenario == "kapi_acik_kaldi":
            temp_off, hum_off = random.uniform(6, 10), random.uniform(5, 12)
        elif scenario == "sogutucu_arizasi":
            temp_off, hum_off = random.uniform(4, 7), 0.0
        elif scenario == "nem_sizinti":
            temp_off, hum_off = 0.0, random.uniform(15, 25)
        else:  # isitici_arizasi
            temp_off, hum_off = -random.uniform(5, 9), 0.0

        self.anomaly = AnomalyState(
            active=True,
            ends_at=time.time() + duration,
            scenario=scenario,
            temp_offset=temp_off,
            humidity_offset=hum_off,
        )
        print(
            f"[ANOMALI] {self.cfg['name']}: {scenario} "
            f"(süre ~{int(duration)}s, dT={temp_off:+.1f}, dH={hum_off:+.1f})"
        )

    def _tick_anomaly(self) -> None:
        """Süresi dolan anomaliyi kapatır."""
        if self.anomaly.active and time.time() >= self.anomaly.ends_at:
            print(f"[ANOMALI-BITTI] {self.cfg['name']}: {self.anomaly.scenario}")
            self.anomaly = AnomalyState()

    def read(self) -> dict:
        """Bir tur sensör okuması üretir."""
        self._maybe_trigger_anomaly()
        self._tick_anomaly()

        temp = self._diurnal(self.cfg["temp_center"], self.cfg["temp_amplitude"])
        temp += random.gauss(0, 0.3)  # sensör gürültüsü

        hum = self._diurnal(self.cfg["humidity_center"], self.cfg["humidity_amplitude"])
        hum += random.gauss(0, 0.8)

        if self.anomaly.active:
            temp += self.anomaly.temp_offset
            hum += self.anomaly.humidity_offset

        return {
            "depo_id": self.depo_id,
            "sicaklik": round(temp, 2),
            "nem": round(max(0.0, min(100.0, hum)), 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "anomali": self.anomaly.scenario if self.anomaly.active else None,
        }


class Publisher:
    """MQTT üzerinden yayın yapan sarmalayıcı."""

    def __init__(self, host: str, port: int):
        self.client = mqtt.Client(client_id=f"simulator-{random.randint(1000, 9999)}")
        self.host = host
        self.port = port
        self._connected = False

    def connect(self) -> None:
        # Broker gecikmesi olabilir (docker-compose'da), tekrar dene
        for attempt in range(1, 11):
            try:
                self.client.connect(self.host, self.port, keepalive=30)
                self.client.loop_start()
                self._connected = True
                print(f"[MQTT] {self.host}:{self.port} bağlantısı kuruldu.")
                return
            except Exception as e:  # broker henüz hazır olmayabilir
                print(f"[MQTT] Bağlantı denemesi {attempt}/10 başarısız: {e}")
                time.sleep(2)
        raise RuntimeError("MQTT broker'a bağlanılamadı.")

    def publish(self, depo_id: str, reading: dict) -> None:
        # Sıcaklık ve nemi ayrı topic'lere yayınlıyoruz (istenildiği gibi)
        payload_temp = {
            "value": reading["sicaklik"],
            "unit": "C",
            "timestamp": reading["timestamp"],
            "anomali": reading["anomali"],
        }
        payload_hum = {
            "value": reading["nem"],
            "unit": "%",
            "timestamp": reading["timestamp"],
            "anomali": reading["anomali"],
        }
        self.client.publish(f"depo/{depo_id}/sicaklik", json.dumps(payload_temp), qos=0)
        self.client.publish(f"depo/{depo_id}/nem", json.dumps(payload_hum), qos=0)

    def close(self) -> None:
        if self._connected:
            self.client.loop_stop()
            self.client.disconnect()


_stop = threading.Event()


def _graceful_exit(signum, frame):
    print("\n[SIM] Kapatılıyor...")
    _stop.set()


def sensor_loop(sensor: WarehouseSensor, publisher: Publisher) -> None:
    """Tek deponun okuma-yayın döngüsü."""
    while not _stop.is_set():
        reading = sensor.read()
        publisher.publish(sensor.depo_id, reading)
        flag = "!" if reading["anomali"] else " "
        print(
            f" {flag} {sensor.cfg['name']:<18} "
            f"T={reading['sicaklik']:>5.2f}°C  H={reading['nem']:>5.2f}%"
        )
        # Her sensör kendi aralığını rastgele seçer, hepsi aynı anda yayın yapmasın
        time.sleep(random.uniform(PUBLISH_INTERVAL_MIN, PUBLISH_INTERVAL_MAX))


def main() -> int:
    signal.signal(signal.SIGINT, _graceful_exit)
    signal.signal(signal.SIGTERM, _graceful_exit)

    publisher = Publisher(MQTT_HOST, MQTT_PORT)
    publisher.connect()

    threads = []
    for depo_id, cfg in WAREHOUSES.items():
        sensor = WarehouseSensor(depo_id=depo_id, cfg=cfg)
        t = threading.Thread(target=sensor_loop, args=(sensor, publisher), daemon=True)
        t.start()
        threads.append(t)

    print(f"[SIM] {len(threads)} depo simüle ediliyor. Ctrl+C ile durdur.")
    try:
        while not _stop.is_set():
            time.sleep(1)
    finally:
        publisher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
