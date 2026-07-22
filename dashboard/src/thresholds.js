/**
 * Which side of its configured range a reading falls on, or null when it
 * is normal (or missing).
 *
 * The bounds are the ones /current carries, which are the same values the
 * backend's threshold detector uses - so the dashboard and the alerts it
 * displays cannot disagree about what "out of range" means.
 */
export function breach(value, min, max) {
  if (value == null) return null
  if (value > max) return 'high'
  if (value < min) return 'low'
  return null
}

/** True when either metric of a /current row is outside its range. */
export function isOutOfRange(warehouse) {
  return Boolean(
    breach(warehouse.temperature, warehouse.temp_min, warehouse.temp_max) ||
    breach(warehouse.humidity, warehouse.hum_min, warehouse.hum_max),
  )
}
