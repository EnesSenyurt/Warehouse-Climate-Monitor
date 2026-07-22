"""FastAPI app - REST + WebSocket + MQTT bridge."""

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import PRUNE_INTERVAL_SECONDS, RETENTION_DAYS, WAREHOUSE_THRESHOLDS
from .mqtt_client import MQTTBridge
from .ws_manager import WSManager

ws_manager = WSManager()
bridge: MQTTBridge | None = None


def retention_cutoff(now: datetime | None = None) -> str | None:
    """
    Timestamp before which rows are eligible for deletion, or None when
    retention is switched off.
    """
    if RETENTION_DAYS <= 0:
        return None
    now = now or datetime.now(UTC)
    return (now - timedelta(days=RETENTION_DAYS)).isoformat()


async def prune_loop() -> None:
    """Deletes aged-out rows on a fixed interval, starting immediately."""
    while True:
        cutoff = retention_cutoff()
        if cutoff:
            try:
                # SQLite deletes block; keep them off the event loop so
                # requests and the WebSocket fan-out are not stalled.
                removed = await asyncio.to_thread(db.prune_older_than, cutoff)
                if removed["readings"] or removed["alerts"]:
                    print(
                        f"[RETENTION] pruned {removed['readings']} reading(s) and "
                        f"{removed['alerts']} alert(s) older than {cutoff}"
                    )
            except Exception as e:
                # A failed prune must not kill the loop - try again next tick
                print(f"[RETENTION] prune failed: {e}")
        await asyncio.sleep(PRUNE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bridge
    db.init_db()
    loop = asyncio.get_running_loop()
    bridge = MQTTBridge(ws_manager, loop)
    bridge.start()

    if RETENTION_DAYS > 0:
        print(f"[RETENTION] keeping {RETENTION_DAYS} day(s) of history")
        pruner = asyncio.create_task(prune_loop())
    else:
        print("[RETENTION] disabled - readings are kept indefinitely")
        pruner = None

    yield

    if pruner:
        pruner.cancel()
        with suppress(asyncio.CancelledError):
            await pruner
    if bridge:
        bridge.stop()


app = FastAPI(title="Warehouse Climate Monitor", lifespan=lifespan)

# Dashboard is served from a different origin (Vite dev at 5173, docker at 8080).
# It's an internal tool, so CORS stays wide open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/warehouses")
def warehouses():
    """Warehouse list + thresholds for the dashboard."""
    return [
        {"id": warehouse_id, **cfg}
        for warehouse_id, cfg in WAREHOUSE_THRESHOLDS.items()
    ]


@app.get("/current")
def current():
    """Latest reading per warehouse."""
    rows = db.latest_per_warehouse()
    by_id = {r["warehouse_id"]: r for r in rows}
    result = []
    for warehouse_id, cfg in WAREHOUSE_THRESHOLDS.items():
        row = by_id.get(warehouse_id)
        result.append({
            "warehouse_id": warehouse_id,
            "name": cfg["name"],
            "temperature": row["temperature"] if row else None,
            "humidity": row["humidity"] if row else None,
            "timestamp": row["timestamp"] if row else None,
            "temp_min": cfg["temp_min"], "temp_max": cfg["temp_max"],
            "hum_min": cfg["hum_min"], "hum_max": cfg["hum_max"],
        })
    return result


@app.get("/history/{warehouse_id}")
def history(warehouse_id: str, hours: float = Query(1.0, ge=0.05, le=168)):
    if warehouse_id not in WAREHOUSE_THRESHOLDS:
        raise HTTPException(status_code=404, detail="Unknown warehouse")
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    return db.history(warehouse_id, since)


@app.get("/alerts")
def alerts(limit: int = Query(100, ge=1, le=1000)):
    return db.recent_alerts(limit)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            # We don't expect messages from the client - just keep the socket alive
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)
    except Exception:
        await ws_manager.disconnect(ws)
