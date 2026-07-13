"""
Depo yapılandırması.
Her sanal deponun kendine özgü normal sıcaklık/nem aralığı vardır.
Böylece "Boya Atölyesi" doğal olarak daha sıcak, "Elektrik Deposu"
daha kuru gibi gerçekçi bir davranış sergiler.
"""

WAREHOUSES = {
    "depo_a": {
        "name": "Depo A",
        "temp_center": 20.0,       # Ortalama sıcaklık (°C)
        "temp_amplitude": 2.5,     # Gün içi dalgalanma genliği
        "temp_min": 15.0,          # Alarm eşiği - alt sınır
        "temp_max": 26.0,          # Alarm eşiği - üst sınır
        "humidity_center": 55.0,   # Ortalama nem (%)
        "humidity_amplitude": 5.0,
        "humidity_min": 40.0,
        "humidity_max": 70.0,
    },
    "depo_b": {
        "name": "Depo B",
        "temp_center": 18.0,
        "temp_amplitude": 2.0,
        "temp_min": 12.0,
        "temp_max": 24.0,
        "humidity_center": 60.0,
        "humidity_amplitude": 6.0,
        "humidity_min": 45.0,
        "humidity_max": 75.0,
    },
    "boya_atolyesi": {
        "name": "Boya Atölyesi",
        "temp_center": 24.0,       # Boya için ideal daha yüksek
        "temp_amplitude": 3.0,
        "temp_min": 18.0,
        "temp_max": 30.0,
        "humidity_center": 45.0,   # Boya için nem düşük olmalı
        "humidity_amplitude": 4.0,
        "humidity_min": 30.0,
        "humidity_max": 60.0,
    },
    "elektrik_deposu": {
        "name": "Elektrik Deposu",
        "temp_center": 19.0,
        "temp_amplitude": 1.5,
        "temp_min": 10.0,
        "temp_max": 25.0,
        "humidity_center": 40.0,   # Elektrik için nem düşük tutulmalı
        "humidity_amplitude": 3.0,
        "humidity_min": 25.0,
        "humidity_max": 55.0,
    },
}

# MQTT ayarları - docker-compose'da 'mosquitto' host'u kullanılır,
# yerelde çalışırken localhost'a düşer.
import os

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# Yayın aralığı - saniye
PUBLISH_INTERVAL_MIN = 5
PUBLISH_INTERVAL_MAX = 10

# Anomali enjeksiyon olasılığı (her yayın için)
ANOMALY_PROBABILITY = 0.02   # %2 ihtimalle anomali başlar
ANOMALY_DURATION_MIN = 30    # Saniye
ANOMALY_DURATION_MAX = 120
