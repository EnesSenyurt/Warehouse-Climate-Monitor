import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid } from 'recharts'
import { freshness } from './freshness'

// The backend sends "reading" events one metric at a time (temperature or
// humidity). Chart wants a single time series so points are merged upstream.
export default function WarehouseCard({ warehouse, series, isAlerted, now }) {
  const data = series.map((row) => ({
    // Show a short HH:MM:SS label on the X axis instead of an ISO string
    t: row.timestamp,
    label: new Date(row.timestamp).toLocaleTimeString(),
    temperature: row.temperature,
    humidity: row.humidity,
  }))

  const latest = data[data.length - 1] || {}
  const updated = freshness(warehouse.timestamp, now)

  // The card as a whole turns red when the warehouse alerts, but that
  // does not say which metric caused it. Compare against the same bounds
  // the backend's threshold detector uses. Returns a direction rather
  // than a flag so the breach is marked by an arrow as well as colour -
  // colour alone should not be the only cue.
  const breach = (value, min, max) => {
    if (value == null) return null
    if (value > max) return 'high'
    if (value < min) return 'low'
    return null
  }
  const tempBreach = breach(latest.temperature, warehouse.temp_min, warehouse.temp_max)
  const humBreach = breach(latest.humidity, warehouse.hum_min, warehouse.hum_max)
  const arrow = (dir) => (dir === 'high' ? ' ▲' : dir === 'low' ? ' ▼' : '')

  return (
    <div className={`warehouse-card ${isAlerted ? 'alert' : ''}`}>
      <div className="warehouse-header">
        <h2>{warehouse.name}</h2>
        <span className={`badge ${isAlerted ? 'err' : 'ok'}`}>
          {isAlerted ? 'ALERT' : 'NORMAL'}
        </span>
      </div>
      <div className="readings">
        <div>
          Temperature{' '}
          <strong className={tempBreach ? 'breach' : ''}>
            {latest.temperature != null ? `${latest.temperature.toFixed(1)}°C` : '-'}
            {arrow(tempBreach)}
          </strong>
        </div>
        <div>
          Humidity{' '}
          <strong className={humBreach ? 'breach' : ''}>
            {latest.humidity != null ? `${latest.humidity.toFixed(1)}%` : '-'}
            {arrow(humBreach)}
          </strong>
        </div>
      </div>

      <div className={`freshness ${updated.stale ? 'stale' : ''}`}>{updated.text}</div>

      <div style={{ height: 180 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -20 }}>
            <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} minTickGap={30} />
            <YAxis yAxisId="t" tick={{ fill: '#f87171', fontSize: 10 }} domain={['auto', 'auto']} />
            <YAxis yAxisId="h" orientation="right" tick={{ fill: '#60a5fa', fontSize: 10 }} domain={[0, 100]} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155' }}
              labelStyle={{ color: '#e2e8f0' }}
            />
            {/* Threshold lines - let the operator eyeball deviations.
                Each pair is tinted like its own series, so it is clear
                which axis a line belongs to. */}
            <ReferenceLine yAxisId="t" y={warehouse.temp_max} stroke="#ef4444" strokeDasharray="4 4" />
            <ReferenceLine yAxisId="t" y={warehouse.temp_min} stroke="#ef4444" strokeDasharray="4 4" />
            <ReferenceLine yAxisId="h" y={warehouse.hum_max} stroke="#3b82f6" strokeDasharray="2 4" />
            <ReferenceLine yAxisId="h" y={warehouse.hum_min} stroke="#3b82f6" strokeDasharray="2 4" />
            <Line yAxisId="t" type="monotone" dataKey="temperature" stroke="#f87171" dot={false} name="°C" isAnimationActive={false} />
            <Line yAxisId="h" type="monotone" dataKey="humidity" stroke="#60a5fa" dot={false} name="%" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
