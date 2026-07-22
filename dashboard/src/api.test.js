/**
 * Tests for openLiveSocket's connection handling.
 *
 * WebSocket and the timers are stubbed, so no server is involved and the
 * retry delay is inspected rather than waited out. Math.random is pinned
 * so the reconnect jitter is deterministic.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openLiveSocket } from './api'

let sockets
let timers

/** The most recent socket handed out by the stubbed constructor. */
const latest = () => sockets[sockets.length - 1]

/** Delay of the retry currently scheduled. */
const pendingDelay = () => timers.filter((t) => !t.cancelled).at(-1).delay

/** Fires every scheduled retry that has not been cancelled. */
function runTimers() {
  const due = timers.splice(0)
  for (const t of due) if (!t.cancelled) t.fn()
}

beforeEach(() => {
  sockets = []
  timers = []

  vi.stubGlobal('WebSocket', class {
    constructor(url) {
      this.url = url
      this.closed = false
      sockets.push(this)
    }
    // A real socket fires onclose when closed, including when the close
    // was requested locally - that is exactly why openLiveSocket detaches
    // the handler first, so the stub has to do it too.
    close() {
      this.closed = true
      this.onclose?.()
    }
  })
  vi.stubGlobal('setTimeout', (fn, delay) => timers.push({ fn, delay }) )
  vi.stubGlobal('clearTimeout', () => timers.forEach((t) => { t.cancelled = true }))
  vi.spyOn(Math, 'random').mockReturnValue(0.5)   // jitter factor -> 0.75
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('openLiveSocket', () => {
  it('connects immediately', () => {
    openLiveSocket({ onMessage: () => {}, onStatus: () => {} })

    expect(sockets).toHaveLength(1)
    expect(latest().url).toMatch(/\/ws$/)
  })

  it('reports connection status', () => {
    const seen = []
    openLiveSocket({ onMessage: () => {}, onStatus: (ok) => seen.push(ok) })

    latest().onopen()
    latest().onclose()

    expect(seen).toEqual([true, false])
  })

  it('delivers parsed messages', () => {
    const seen = []
    openLiveSocket({ onMessage: (m) => seen.push(m), onStatus: () => {} })

    latest().onmessage({ data: '{"type":"reading","value":21.5}' })

    expect(seen).toEqual([{ type: 'reading', value: 21.5 }])
  })

  it('survives a malformed frame', () => {
    const seen = []
    vi.spyOn(console, 'error').mockImplementation(() => {})
    openLiveSocket({ onMessage: (m) => seen.push(m), onStatus: () => {} })

    latest().onmessage({ data: 'not json' })
    latest().onmessage({ data: '{"ok":true}' })

    expect(seen).toEqual([{ ok: true }])
  })

  it('reconnects after an unexpected close', () => {
    openLiveSocket({ onMessage: () => {}, onStatus: () => {} })

    latest().onclose()
    expect(sockets).toHaveLength(1)      // scheduled, not reopened yet

    runTimers()
    expect(sockets).toHaveLength(2)
  })

  it('backs off further on each successive failure', () => {
    openLiveSocket({ onMessage: () => {}, onStatus: () => {} })

    latest().onclose()
    const first = pendingDelay()
    runTimers()

    latest().onclose()

    expect(pendingDelay()).toBeGreaterThan(first)
  })

  it('caps the backoff', () => {
    openLiveSocket({ onMessage: () => {}, onStatus: () => {} })

    for (let i = 0; i < 20; i++) {
      latest().onclose()
      runTimers()
    }
    latest().onclose()

    expect(pendingDelay()).toBeLessThanOrEqual(30000)
  })

  it('resets the backoff once a connection succeeds', () => {
    openLiveSocket({ onMessage: () => {}, onStatus: () => {} })

    latest().onclose()
    runTimers()
    latest().onclose()
    const grown = pendingDelay()
    runTimers()

    latest().onopen()                    // a good connection
    latest().onclose()

    expect(pendingDelay()).toBeLessThan(grown)
  })

  it('stops reconnecting after close()', () => {
    const handle = openLiveSocket({ onMessage: () => {}, onStatus: () => {} })

    handle.close()
    expect(latest().closed).toBe(true)

    runTimers()
    expect(sockets).toHaveLength(1)
  })

  it('does not reconnect when close() races an in-flight retry', () => {
    const handle = openLiveSocket({ onMessage: () => {}, onStatus: () => {} })

    latest().onclose()                   // retry scheduled
    handle.close()
    runTimers()

    expect(sockets).toHaveLength(1)
  })
})
