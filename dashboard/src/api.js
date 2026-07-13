// Single entry point for backend calls.
// Inside docker-compose the host differs, so allow override via env var.
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const WS_BASE = import.meta.env.VITE_WS_BASE ||
  API_BASE.replace(/^http/, 'ws')

export async function fetchCurrent() {
  const r = await fetch(`${API_BASE}/current`)
  if (!r.ok) throw new Error('current fetch failed')
  return r.json()
}

export async function fetchHistory(warehouseId, hours) {
  const r = await fetch(`${API_BASE}/history/${warehouseId}?hours=${hours}`)
  if (!r.ok) throw new Error('history fetch failed')
  return r.json()
}

export async function fetchAlerts(limit = 50) {
  const r = await fetch(`${API_BASE}/alerts?limit=${limit}`)
  if (!r.ok) throw new Error('alerts fetch failed')
  return r.json()
}

export function openLiveSocket(onMessage) {
  const url = `${WS_BASE}/ws`
  const ws = new WebSocket(url)
  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data)
      onMessage(data)
    } catch (e) {
      console.error('ws parse error', e)
    }
  }
  return ws
}
