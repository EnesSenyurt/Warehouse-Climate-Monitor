import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid } from 'recharts'

// The backend sends "reading" events one metric at a time (temperature or
// humidity). Chart wants a single time series so points are merged upstream.
export default function WarehouseCard({ warehouse, series, isAlerted }) {
  const data = series.map((row) => ({
    // Show a short HH:MM:SS label on the X axis instead of an ISO string
    t: row.timestamp,
    label: new Date(row.timestamp).toLocaleTimeString(),
    temperature: row.temperature,
    humidity: row.humidity,
  }))

  const latest = data[data.length - 1] || {}

  return (
    <div className={`warehouse-card ${isAlerted ? 'alert' : ''}`}>
      <div className="warehouse-header">
        <h2>{warehouse.name}</h2>
        <span className={`badge ${isAlerted ? 'err' : 'ok'}`}>
          {isAlerted ? 'ALERT' : 'NORMAL'}
        </span>
      </div>
      <div className="readings">
        <div>Temperature <strong>{latest.temperature != null ? `${latest.temperature.toFixed(1)}°C` : '-'}</strong></div>
        <div>Humidity <strong>{latest.humidity != null ? `${latest.humidity.toFixed(1)}%` : '-'}</strong></div>
      </div>

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
            {/* Threshold lines - let the operator eyeball deviations */}
            <ReferenceLine yAxisId="t" y={warehouse.temp_max} stroke="#ef4444" strokeDasharray="4 4" />
            <ReferenceLine yAxisId="t" y={warehouse.temp_min} stroke="#ef4444" strokeDasharray="4 4" />
            <Line yAxisId="t" type="monotone" dataKey="temperature" stroke="#f87171" dot={false} name="°C" isAnimationActive={false} />
            <Line yAxisId="h" type="monotone" dataKey="humidity" stroke="#60a5fa" dot={false} name="%" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
