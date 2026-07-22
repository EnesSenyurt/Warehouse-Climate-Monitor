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

const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000

/**
 * Opens the live stream and keeps it open. The backend restarting, or a
 * dropped network, previously left the dashboard frozen until someone
 * reloaded the page - the socket closed and nothing reopened it.
 *
 * Returns a handle with close(); call it on unmount.
 */
export function openLiveSocket({ onMessage, onStatus }) {
  const url = `${WS_BASE}/ws`
  let ws = null
  let attempt = 0
  let retryTimer = null
  let stopped = false

  function scheduleReconnect() {
    if (stopped) return
    // Exponential backoff, capped, with jitter so that every open
    // dashboard doesn't retry in lockstep against a restarting backend.
    const backoff = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS)
    attempt += 1
    retryTimer = setTimeout(connect, backoff * (0.5 + Math.random() / 2))
  }

  function connect() {
    if (stopped) return
    ws = new WebSocket(url)

    ws.onopen = () => {
      attempt = 0          // a good connection resets the backoff
      onStatus?.(true)
    }
    ws.onmessage = (evt) => {
      try {
        onMessage(JSON.parse(evt.data))
      } catch (e) {
        console.error('ws parse error', e)
      }
    }
    // onerror is always followed by onclose, so reconnect from one place
    ws.onclose = () => {
      onStatus?.(false)
      scheduleReconnect()
    }
  }

  connect()

  return {
    close() {
      stopped = true
      clearTimeout(retryTimer)
      if (ws) {
        ws.onclose = null   // an intentional close must not reconnect
        ws.close()
      }
    },
  }
}
