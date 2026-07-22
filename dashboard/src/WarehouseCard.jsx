import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid, Legend } from 'recharts'
import { freshness } from './freshness'
import { breach } from './thresholds'

// The backend sends "reading" events one metric at a time (temperature or
// humidity). Chart wants a single time series so points are merged upstream.
export default function WarehouseCard({ warehouse, series, isAlerted, now }) {
  const data = series.map((row) => ({
    // HH:MM on the axis - at one sample every few seconds the seconds
    // are noise, and the shorter label lets more ticks fit.
    t: row.timestamp,
    // hour12:false, or an en-US browser renders "01:10 PM" - longer than
    // the label this replaced, and inconsistent with other locales.
    label: new Date(row.timestamp).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit', hour12: false,
    }),
    // The tooltip is where the exact instant is worth having
    fullLabel: new Date(row.timestamp).toLocaleTimeString(),
    temperature: row.temperature,
    humidity: row.humidity,
  }))

  const latest = data[data.length - 1] || {}
  const updated = freshness(warehouse.timestamp, now)

  // The card as a whole turns red when the warehouse alerts, but that
  // does not say which metric caused it. The arrow means colour is not
  // the only cue, and the direction is useful in its own right.
  const tempBreach = breach(latest.temperature, warehouse.temp_min, warehouse.temp_max)
  const humBreach = breach(latest.humidity, warehouse.hum_min, warehouse.hum_max)
  const arrow = (dir) => (dir === 'high' ? ' ▲' : dir === 'low' ? ' ▼' : '')

  return (
    <div className={`warehouse-card ${isAlerted ? 'alert' : ''}`}>
      <div className="warehouse-header">
        <h2>{warehouse.name}</h2>
        {/* A silent feed means the current state is unknown, so the badge
            says so rather than vouching for the last reading. */}
        <span className={`badge ${updated.stale ? 'warn' : isAlerted ? 'err' : 'ok'}`}>
          {updated.stale ? 'STALE' : isAlerted ? 'ALERT' : 'NORMAL'}
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

      {/* 200 rather than 180: the legend takes 20px off the plot area */}
      <div style={{ height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} minTickGap={30} />
            {/* Explicit widths instead of pulling the axis in with a
                negative margin, which clipped wider tick labels. */}
            <YAxis yAxisId="t" width={34} tick={{ fill: '#f87171', fontSize: 10 }} domain={['auto', 'auto']} />
            <YAxis yAxisId="h" width={30} orientation="right" tick={{ fill: '#60a5fa', fontSize: 10 }} domain={[0, 100]} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155' }}
              labelStyle={{ color: '#e2e8f0' }}
              labelFormatter={(_, payload) => payload?.[0]?.payload.fullLabel ?? ''}
            />
            {/* Threshold lines - let the operator eyeball deviations.
                Each pair is tinted like its own series, so it is clear
                which axis a line belongs to. */}
            <ReferenceLine yAxisId="t" y={warehouse.temp_max} stroke="#ef4444" strokeDasharray="4 4" />
            <ReferenceLine yAxisId="t" y={warehouse.temp_min} stroke="#ef4444" strokeDasharray="4 4" />
            <ReferenceLine yAxisId="h" y={warehouse.hum_max} stroke="#3b82f6" strokeDasharray="2 4" />
            <ReferenceLine yAxisId="h" y={warehouse.hum_min} stroke="#3b82f6" strokeDasharray="2 4" />
            {/* Two series on two differently-scaled axes; without this the
                only cue tying a line to its axis is the tick colour. */}
            <Legend verticalAlign="top" height={20} iconSize={8}
                    wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
            <Line yAxisId="t" type="monotone" dataKey="temperature" stroke="#f87171" dot={false} name="Temperature (°C)" isAnimationActive={false} />
            <Line yAxisId="h" type="monotone" dataKey="humidity" stroke="#60a5fa" dot={false} name="Humidity (%)" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
