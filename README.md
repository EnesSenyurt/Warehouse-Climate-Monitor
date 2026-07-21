# Warehouse Climate Monitor

An **end-to-end IoT simulation** for warehouse temperature/humidity
monitoring. No hardware is used; sensors are simulated in software and
their readings flow over MQTT to a backend. The goal is to demonstrate
every layer of a real IoT pipeline (sensor → broker → backend → database
→ dashboard) with a small runnable example.

## Architecture

```
+-------------------+       MQTT        +---------------------+
| sensor_simulator  |  ---------------> |     Mosquitto       |
|  (Python)         |  warehouse/+/     |     (broker)        |
|  4 virtual        |    temperature    |                     |
|  warehouses       |  warehouse/+/     |                     |
|                   |    humidity       |                     |
+-------------------+                    +---------+-----------+
                                                   |
                                                   | subscribe
                                                   v
                                        +----------+-----------+
                                        |    FastAPI backend   |
                                        |  - MQTT subscriber   |
                                        |  - SQLite storage    |
                                        |  - Anomaly detection |
                                        |  - REST + WebSocket  |
                                        +----------+-----------+
                                                   |
                                       REST / WS   |
                                                   v
                                         +---------+---------+
                                         |  React Dashboard  |
                                         |  - Live charts    |
                                         |  - Alert banner   |
                                         +-------------------+
```

## Components

- **sensor_simulator/** — 4 virtual warehouses. Each has its own normal
  temperature/humidity range; readings are produced by a sine wave +
  Gaussian noise, with occasional random anomaly scenarios (door left
  open, cooler failure, humidity leak, heater failure). Publishes to
  `warehouse/{id}/temperature` and `warehouse/{id}/humidity` over MQTT.
- **backend/** — FastAPI. Subscribes to MQTT, stores readings in SQLite,
  runs a two-layer anomaly detector (threshold + z-score), and exposes
  REST and WebSocket endpoints.
- **dashboard/** — React + Vite + recharts. Live temperature/humidity
  charts, time-range filter, status summary, alert banner.
- **mosquitto/** — Eclipse Mosquitto configuration.

## Quick start (Docker)

Brings the whole stack up with a single command:

```bash
docker compose up --build
```

Services:
- Dashboard: http://localhost:8080
- Backend REST + Swagger: http://localhost:8000/docs
- Mosquitto: `localhost:1883`

Tear down:
```bash
docker compose down
```
Add `-v` to also remove volumes.

## Local development (without Docker)

You still need Mosquitto. The easiest setup is to run just the broker in
Docker while running the Python/Node services natively:

```bash
docker run --rm -it -p 1883:1883 \
  -v "$(pwd)/mosquitto/config:/mosquitto/config" \
  eclipse-mosquitto:2
```

In separate terminals:

```bash
# Simulator
cd sensor_simulator
pip install -r requirements.txt
python simulator.py

# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Dashboard
cd dashboard
npm install
npm run dev
```

Dashboard: http://localhost:5173

## API endpoints

| Method | Path                                | Description                              |
|--------|-------------------------------------|------------------------------------------|
| GET    | `/warehouses`                       | Warehouse list + thresholds              |
| GET    | `/current`                          | Latest reading per warehouse             |
| GET    | `/history/{warehouse_id}?hours=1`   | Historical readings for the given window |
| GET    | `/alerts?limit=100`                 | Most recent alerts                       |
| GET    | `/health`                           | Health check                             |
| WS     | `/ws`                               | Live reading stream (JSON messages)      |

## Anomaly detection

Two detectors run in parallel:

1. **Threshold** — each warehouse has a `[min, max]` normal range.
   Values outside it raise a `threshold` alert.
2. **Z-score** — a rolling window of the last 30 samples. An alert is
   raised when `|z| > 3`. Catches sudden jumps even when the value is
   still within the threshold band.

Alerts are de-duplicated: while a given warehouse/metric/detector keeps
firing, repeats are suppressed for `ALERT_COOLDOWN_SECONDS` (60 s by
default, in `backend/app/config.py`). Without this a two-minute anomaly
would write an alert row for every reading. The cooldown resets as soon
as the metric reads normal again, so a new episode always alerts right
away.

## Sensor smoke test

To validate just the sensor logic without a broker:

```bash
cd sensor_simulator
python test_local.py
```

## Project layout

```
Warehouse-Climate-Monitor/
├── sensor_simulator/       # Python - virtual sensors
├── backend/                # FastAPI + MQTT + SQLite
│   └── app/
├── dashboard/              # React + Vite
│   └── src/
├── mosquitto/config/       # Broker configuration
├── docker-compose.yml
└── README.md
```

## Integrating real sensors

Real hardware simply replaces the simulator; **the backend needs no
changes** because both sides talk MQTT with the same topic schema.

Example with an ESP32 + DHT22 (or SHT31, BME280):

1. The device joins Wi-Fi.
2. It connects to Mosquitto via a client library (`paho-mqtt` on
   MicroPython, `PubSubClient` on Arduino, etc.).
3. Every N seconds it publishes a reading to:
   ```
   warehouse/{device_id}/temperature
   warehouse/{device_id}/humidity
   ```
   Payload:
   ```json
   {"value": 22.4, "unit": "C", "timestamp": "2026-07-13T09:00:00Z"}
   ```
4. Add a new entry in the backend's `WAREHOUSE_THRESHOLDS` config with
   the device's `id`, display name and threshold values.

If the deployment grows, things to consider:
- Authentication + TLS on the broker (Mosquitto `password_file` / certs).
- Swap SQLite for PostgreSQL or a time-series DB (InfluxDB, TimescaleDB).
- Scale the backend horizontally and use MQTT shared subscriptions.
- Retention / downsampling policy for long-term storage.

## Notes

- The simulator sends temperature and humidity on separate topics. The
  backend merges them into a single row when timestamps line up
  (`upsert_last_reading`).
- The diurnal cycle is compressed to **10 minutes** so a full "day" is
  observable during a demo (`sensor_simulator/simulator.py`,
  `period_seconds`).
