import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchAlerts, fetchCurrent, fetchHistory, openLiveSocket } from './api'
import WarehouseCard from './WarehouseCard'

const RANGES = [
  { label: 'Last 1h', hours: 1 },
  { label: 'Last 6h', hours: 6 },
  { label: 'Last 24h', hours: 24 },
]

// A warehouse is treated as "in alert" if it fired within the last 60 s.
const RECENT_ALERT_MS = 60_000

export default function App() {
  const [current, setCurrent] = useState([])          // /current response
  const [alerts, setAlerts] = useState([])            // recent alerts
  const [range, setRange] = useState(RANGES[0].hours)
  const [series, setSeries] = useState({})            // warehouseId -> [{timestamp, temperature, humidity}]
  const [wsOk, setWsOk] = useState(false)

  // We keep the current series in a ref so per-message updates don't need
  // to snapshot the full state - only the affected warehouse's series is
  // rebuilt on each incoming reading.
  const seriesRef = useRef({})
  seriesRef.current = series

  // Initial load: current values + history + recent alerts
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const cur = await fetchCurrent()
        if (cancelled) return
        setCurrent(cur)

        // History for every warehouse, respecting the selected range
        const results = await Promise.all(
          cur.map((w) => fetchHistory(w.warehouse_id, range).then((rows) => [w.warehouse_id, rows])),
        )
        if (cancelled) return
        const next = {}
        for (const [id, rows] of results) next[id] = rows
        setSeries(next)

        const a = await fetchAlerts(50)
        if (!cancelled) setAlerts(a)
      } catch (e) {
        console.error(e)
      }
    }
    load()
    return () => { cancelled = true }
  }, [range])

  // WebSocket - live stream
  useEffect(() => {
    const ws = openLiveSocket((msg) => {
      if (msg.type !== 'reading') return

      // Merge logic - if the latest sample for this warehouse arrived
      // within the last 3 s, update it in place; otherwise append.
      const prev = seriesRef.current[msg.warehouse_id] || []
      const last = prev[prev.length - 1]
      const nextRow = last ? { ...last } : { timestamp: msg.timestamp, temperature: null, humidity: null }

      const now = new Date(msg.timestamp).getTime()
      const lastT = last ? new Date(last.timestamp).getTime() : 0
      const closeInTime = last && Math.abs(now - lastT) < 3000

      if (msg.metric === 'temperature') nextRow.temperature = msg.value
      else nextRow.humidity = msg.value
      nextRow.timestamp = msg.timestamp

      let updated
      if (closeInTime) {
        updated = [...prev.slice(0, -1), nextRow]
      } else {
        updated = [...prev, nextRow]
      }
      // Rough memory cap for the selected range (~one sample per 5 s)
      const maxPoints = Math.ceil((range * 3600) / 5)
      if (updated.length > maxPoints) updated = updated.slice(updated.length - maxPoints)

      setSeries((s) => ({ ...s, [msg.warehouse_id]: updated }))

      // Update the big number shown at the top of the card
      setCurrent((c) => c.map((w) => {
        if (w.warehouse_id !== msg.warehouse_id) return w
        return {
          ...w,
          temperature: msg.metric === 'temperature' ? msg.value : w.temperature,
          humidity: msg.metric === 'humidity' ? msg.value : w.humidity,
          timestamp: msg.timestamp,
        }
      }))

      // Prepend any new alerts
      if (msg.alerts && msg.alerts.length) {
        setAlerts((a) => [...msg.alerts, ...a].slice(0, 100))
      }
    })
    ws.onopen = () => setWsOk(true)
    ws.onclose = () => setWsOk(false)
    ws.onerror = () => setWsOk(false)
    return () => ws.close()
  }, [range])

  // Warehouses whose alerts landed within the last 60 s are shown as alerting
  const alertedIds = useMemo(() => {
    const now = Date.now()
    const s = new Set()
    for (const a of alerts) {
      const t = new Date(a.timestamp).getTime()
      if (now - t < RECENT_ALERT_MS) s.add(a.warehouse_id)
    }
    return s
  }, [alerts])

  const summary = useMemo(() => {
    const total = current.length
    const alerted = current.filter((w) => alertedIds.has(w.warehouse_id)).length
    return { total, alerted, normal: total - alerted }
  }, [current, alertedIds])

  return (
    <>
      <header>
        <h1>Warehouse Climate Monitor</h1>
        <div style={{ fontSize: 13, color: '#94a3b8' }}>
          <span className={`status-dot ${wsOk ? 'ok' : 'err'}`} />
          {wsOk ? 'Live connection' : 'Waiting for connection'}
        </div>
      </header>

      <div className="container">
        {summary.alerted > 0 && (
          <div className="alerts-banner">
            ⚠ {summary.alerted} warehouse(s) currently reporting anomalies.
          </div>
        )}

        <div className="summary">
          <div className="summary-card"><div>Total warehouses</div><div className="value">{summary.total}</div></div>
          <div className="summary-card ok"><div>Normal</div><div className="value">{summary.normal}</div></div>
          <div className="summary-card err"><div>Alerting</div><div className="value">{summary.alerted}</div></div>
        </div>

        <div className="controls">
          {RANGES.map((r) => (
            <button
              key={r.hours}
              className={range === r.hours ? 'active' : ''}
              onClick={() => setRange(r.hours)}
            >
              {r.label}
            </button>
          ))}
        </div>

        <div className="grid">
          {current.map((w) => (
            <WarehouseCard
              key={w.warehouse_id}
              warehouse={w}
              series={series[w.warehouse_id] || []}
              isAlerted={alertedIds.has(w.warehouse_id)}
            />
          ))}
        </div>

        <div className="alerts-list">
          <h2>Recent Alerts</h2>
          {alerts.length === 0 && <div style={{ color: '#94a3b8', fontSize: 13 }}>No alerts yet.</div>}
          {alerts.slice(0, 20).map((a) => (
            <div key={a.id} className="item">
              <span className="depo">{a.warehouse_id}</span>{' · '}
              <span className="type">{a.alert_type}</span>{' · '}
              {a.message}{' · '}
              <span style={{ color: '#64748b' }}>{new Date(a.timestamp).toLocaleTimeString()}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
