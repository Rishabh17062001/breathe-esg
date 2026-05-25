import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

function StatCard({ label, value, sub, color }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color || 'text-gray-900'}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}

const STATUS_COLORS = {
  PENDING: 'bg-yellow-100 text-yellow-800',
  APPROVED: 'bg-green-100 text-green-800',
  FLAGGED: 'bg-red-100 text-red-800',
  REJECTED: 'bg-gray-100 text-gray-600',
  LOCKED: 'bg-blue-100 text-blue-800',
  COMPLETE: 'bg-green-100 text-green-800',
  PARTIAL: 'bg-yellow-100 text-yellow-800',
  FAILED: 'bg-red-100 text-red-800',
  PROCESSING: 'bg-blue-100 text-blue-800',
}

const SOURCE_LABELS = {
  SAP_FUEL: 'SAP Fuel',
  SAP_PROCUREMENT: 'SAP Procurement',
  UTILITY_ELECTRICITY: 'Electricity',
  TRAVEL_AIR: 'Air Travel',
  TRAVEL_HOTEL: 'Hotel',
  TRAVEL_GROUND: 'Ground',
  TRAVEL_RAIL: 'Rail',
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.dashboard().then(setStats).catch(e => setError(e.message))
  }, [])

  if (error) return <div className="text-red-600 p-4">Failed to load dashboard: {error}</div>
  if (!stats) return <div className="text-gray-500 p-4">Loading...</div>

  const total = stats.total_co2e_tonnes
  const scopePct = (val) => total > 0 ? ((val / total) * 100).toFixed(1) : '0'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Emissions Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">Acme Industries Ltd — Q1 2024</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total CO₂e" value={`${total.toLocaleString(undefined, { maximumFractionDigits: 1 })} t`} sub="All scopes" color="text-green-700" />
        <StatCard label="Total Records" value={stats.total_records} sub={`${stats.pending_count} pending review`} />
        <StatCard label="Flagged" value={stats.flagged_count} sub="Need attention" color={stats.flagged_count > 0 ? 'text-red-600' : 'text-gray-900'} />
        <StatCard label="Approved" value={stats.approved_count} sub={`${stats.rejected_count} rejected`} color="text-green-700" />
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Scope Breakdown</h2>
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Scope 1 — Direct', value: stats.scope1_co2e_tonnes, color: 'bg-green-500' },
            { label: 'Scope 2 — Electricity', value: stats.scope2_co2e_tonnes, color: 'bg-blue-500' },
            { label: 'Scope 3 — Value Chain', value: stats.scope3_co2e_tonnes, color: 'bg-purple-500' },
          ].map(s => (
            <div key={s.label}>
              <div className="flex items-baseline justify-between mb-1">
                <span className="text-xs text-gray-500">{s.label}</span>
                <span className="text-xs font-medium text-gray-700">{scopePct(s.value)}%</span>
              </div>
              <div className="h-2 rounded-full bg-gray-100">
                <div className={`h-2 rounded-full ${s.color}`} style={{ width: `${scopePct(s.value)}%` }} />
              </div>
              <div className="text-lg font-bold text-gray-900 mt-1.5">
                {s.value.toLocaleString(undefined, { maximumFractionDigits: 1 })} t
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">By Source</h2>
          {stats.source_breakdown.length === 0 && (
            <p className="text-sm text-gray-400">No data yet. Upload a file to get started.</p>
          )}
          <div className="space-y-2">
            {stats.source_breakdown.map(s => (
              <div key={s.source_type} className="flex items-center justify-between text-sm">
                <span className="text-gray-600">{SOURCE_LABELS[s.source_type] || s.source_type}</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-400">{s.count} records</span>
                  <span className="font-medium text-gray-900">{s.co2e_tonnes.toLocaleString(undefined, { maximumFractionDigits: 1 })} t</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-700">Recent Uploads</h2>
            <Link to="/batches" className="text-xs text-green-600 hover:underline">View all</Link>
          </div>
          {stats.recent_batches.length === 0 && (
            <p className="text-sm text-gray-400">No uploads yet.</p>
          )}
          <div className="space-y-2">
            {stats.recent_batches.map(b => (
              <div key={b.id} className="flex items-center justify-between text-sm">
                <div>
                  <div className="font-medium text-gray-800 truncate max-w-[180px]">{b.filename}</div>
                  <div className="text-xs text-gray-400">{b.source_type_display} · {new Date(b.created_at).toLocaleDateString()}</div>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[b.status] || 'bg-gray-100 text-gray-600'}`}>
                  {b.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {stats.pending_count > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-center justify-between">
          <div>
            <div className="font-medium text-yellow-800">{stats.pending_count} records pending review</div>
            <div className="text-sm text-yellow-700 mt-0.5">Approve or flag before locking for audit.</div>
          </div>
          <Link to="/records?status=PENDING" className="bg-yellow-600 text-white text-sm px-4 py-2 rounded-md hover:bg-yellow-700 transition-colors">
            Review now
          </Link>
        </div>
      )}
    </div>
  )
}
