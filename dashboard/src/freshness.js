// A warehouse publishes every 5-10 s, so a minute of silence means the
// feed has stopped rather than just being between readings.
const STALE_MS = 60_000

/** "Updated 14:23:07", or how long the feed has been silent. */
export function freshness(timestamp, now) {
  if (!timestamp) return { text: 'No data yet', stale: true }

  const t = new Date(timestamp).getTime()
  const age = now - t
  if (age <= STALE_MS) {
    return { text: `Updated ${new Date(t).toLocaleTimeString()}`, stale: false }
  }

  const minutes = Math.floor(age / 60_000)
  const silence = minutes < 60
    ? `${minutes} min`
    : `${Math.floor(minutes / 60)} h ${minutes % 60} min`
  return { text: `No data for ${silence}`, stale: true }
}
