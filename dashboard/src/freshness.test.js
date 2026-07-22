import { describe, expect, it } from 'vitest'
import { freshness } from './freshness'

const NOW = new Date('2026-07-22T12:00:00Z').getTime()
const ago = (ms) => new Date(NOW - ms).toISOString()

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE

describe('freshness', () => {
  it('treats a warehouse that has never reported as stale', () => {
    expect(freshness(null, NOW)).toEqual({ text: 'No data yet', stale: true })
  })

  it('reports a recent reading as fresh', () => {
    const { stale, text } = freshness(ago(5 * SECOND), NOW)

    expect(stale).toBe(false)
    expect(text).toMatch(/^Updated /)
  })

  it('still counts exactly one minute of silence as fresh', () => {
    expect(freshness(ago(MINUTE), NOW).stale).toBe(false)
  })

  it('flags a feed that has gone quiet', () => {
    expect(freshness(ago(MINUTE + SECOND), NOW)).toEqual({
      text: 'No data for 1 min', stale: true,
    })
  })

  it('rounds the silence down to whole minutes', () => {
    expect(freshness(ago(5 * MINUTE + 59 * SECOND), NOW).text).toBe('No data for 5 min')
  })

  it('switches to hours once the gap is long enough', () => {
    expect(freshness(ago(2 * HOUR + 7 * MINUTE), NOW).text).toBe('No data for 2 h 7 min')
  })

  it('does not report a whole hour as 60 min', () => {
    expect(freshness(ago(HOUR), NOW).text).toBe('No data for 1 h 0 min')
  })
})
