import { describe, expect, it } from 'vitest'
import { breach, isOutOfRange } from './thresholds'

const row = (over) => ({
  temperature: 20, humidity: 55,
  temp_min: 15, temp_max: 26, hum_min: 40, hum_max: 70,
  ...over,
})

describe('breach', () => {
  it('returns null inside the range', () => {
    expect(breach(20, 15, 26)).toBeNull()
  })

  it('treats the bounds themselves as normal', () => {
    expect(breach(15, 15, 26)).toBeNull()
    expect(breach(26, 15, 26)).toBeNull()
  })

  it('reports which side was crossed', () => {
    expect(breach(26.1, 15, 26)).toBe('high')
    expect(breach(14.9, 15, 26)).toBe('low')
  })

  it('treats a missing reading as normal rather than a breach', () => {
    expect(breach(null, 15, 26)).toBeNull()
    expect(breach(undefined, 15, 26)).toBeNull()
  })

  it('does not mistake 0 for a missing value', () => {
    expect(breach(0, 15, 26)).toBe('low')
  })
})

describe('isOutOfRange', () => {
  it('is false for a normal row', () => {
    expect(isOutOfRange(row())).toBe(false)
  })

  it('catches a temperature breach', () => {
    expect(isOutOfRange(row({ temperature: 30 }))).toBe(true)
  })

  it('catches a humidity breach', () => {
    expect(isOutOfRange(row({ humidity: 80 }))).toBe(true)
  })

  it('is false for a warehouse that has not reported', () => {
    expect(isOutOfRange(row({ temperature: null, humidity: null }))).toBe(false)
  })
})
