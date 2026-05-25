import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { ToastContainer, useToast } from '../components/Toast'

const STATUS_BADGE = {
  PENDING: 'bg-yellow-100 text-yellow-800',
  APPROVED: 'bg-green-100 text-green-800',
  FLAGGED: 'bg-red-100 text-red-700',
  REJECTED: 'bg-gray-100 text-gray-600',
  LOCKED: 'bg-blue-100 text-blue-800',
}

const SCOPE_BADGE = {
  '1': 'bg-green-50 text-green-700 border border-green-200',
  '2': 'bg-blue-50 text-blue-700 border border-blue-200',
  '3': 'bg-purple-50 text-purple-700 border border-purple-200',
}

const SOURCE_SHORT = {
  SAP_FUEL: 'SAP Fuel',
  SAP_PROCUREMENT: 'SAP Proc.',
  UTILITY_ELECTRICITY: 'Electricity',
  TRAVEL_AIR: 'Air',
  TRAVEL_HOTEL: 'Hotel',
  TRAVEL_GROUND: 'Ground',
  TRAVEL_RAIL: 'Rail',
}

function RecordDetail({ record, onAction, showToast }) {
  const [actor, setActor] = useState('analyst')
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)

  const ACTION_MESSAGES = {
    approve: { msg: 'Record approved', type: 'success' },
    flag:    { msg: 'Record flagged for review', type: 'warning' },
    reject:  { msg: 'Record rejected', type: 'error' },
    lock:    { msg: 'Record locked for audit', type: 'info' },
  }

  async function doAction(action) {
    if (!actor) return
    setLoading(true)
    try {
      await api.recordAction(record.id, action, actor, reason)
      const { msg, type } = ACTION_MESSAGES[action] || { msg: 'Done', type: 'success' }
      showToast(msg, type)
      onAction()
    } catch (err) {
      showToast(err.message || 'Action failed', 'error')
    } finally {
      setLoading(false)
      setReason('')
    }
  }

  const locked = record.status === 'LOCKED'

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div><div className="text-xs text-gray-400">Source</div><div className="font-medium text-gray-800">{record.source_type_display}</div></div>
        <div><div className="text-xs text-gray-400">Scope</div><div className="font-medium text-gray-800">{record.scope_display}</div></div>
        <div><div className="text-xs text-gray-400">Date</div><div className="font-medium text-gray-800">{record.activity_date}</div></div>
        <div><div className="text-xs text-gray-400">Category</div><div className="font-medium text-gray-800">{record.category}</div></div>
        <div><div className="text-xs text-gray-400">Quantity (raw)</div><div className="font-medium text-gray-800">{record.raw_quantity} {record.raw_unit}</div></div>
        <div><div className="text-xs text-gray-400">Quantity (normalised)</div><div className="font-medium text-gray-800">{parseFloat(record.quantity_normalized).toLocaleString()} {record.unit_normalized}</div></div>
        <div>
          <div className="text-xs text-gray-400">CO₂e</div>
          <div className="font-bold text-gray-900">{record.co2e_kg ? `${(parseFloat(record.co2e_kg)/1000).toFixed(3)} t` : '—'}</div>
        </div>
        <div><div className="text-xs text-gray-400">Emission factor</div><div className="font-medium text-gray-800">{record.emission_factor || '—'} {record.emission_factor_unit}</div></div>
        {record.location_label && (
          <div className="col-span-2"><div className="text-xs text-gray-400">Location</div><div className="font-medium text-gray-800">{record.location_label}</div></div>
        )}
        {record.vendor_supplier && (
          <div className="col-span-2"><div className="text-xs text-gray-400">Vendor / Supplier</div><div className="font-medium text-gray-800">{record.vendor_supplier}</div></div>
        )}
        {record.description && (
          <div className="col-span-2"><div className="text-xs text-gray-400">Description</div><div className="font-medium text-gray-800">{record.description}</div></div>
        )}
        <div><div className="text-xs text-gray-400">EF source</div><div className="text-gray-700">{record.emission_factor_source || '—'}</div></div>
        <div>
          <div className="text-xs text-gray-400">Confidence</div>
          <div className={`font-medium ${record.confidence_score < 0.7 ? 'text-red-600' : 'text-gray-800'}`}>
            {(record.confidence_score * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      {record.flag_reason && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
          <span className="font-medium">Flag: </span>{record.flag_reason}
        </div>
      )}

      {record.approved_by && (
        <div className="text-xs text-gray-400">Approved by {record.approved_by} on {record.approved_at ? new Date(record.approved_at).toLocaleString() : '—'}</div>
      )}

      {!locked && (
        <div className="border-t pt-4 space-y-3">
          <input type="text" value={actor} onChange={e => setActor(e.target.value)} className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" placeholder="Your name" />
          <input type="text" value={reason} onChange={e => setReason(e.target.value)} className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" placeholder="Reason (required for Flag / Reject)" />
          <div className="flex gap-2">
            <button onClick={() => doAction('approve')} disabled={loading || record.status === 'APPROVED'} className="flex-1 bg-green-600 text-white text-xs py-2 rounded hover:bg-green-700 disabled:opacity-40">Approve</button>
            <button onClick={() => doAction('flag')} disabled={loading || !reason} className="flex-1 bg-yellow-500 text-white text-xs py-2 rounded hover:bg-yellow-600 disabled:opacity-40">Flag</button>
            <button onClick={() => doAction('reject')} disabled={loading} className="flex-1 bg-gray-500 text-white text-xs py-2 rounded hover:bg-gray-600 disabled:opacity-40">Reject</button>
            {record.status === 'APPROVED' && (
              <button onClick={() => doAction('lock')} disabled={loading} className="flex-1 bg-blue-600 text-white text-xs py-2 rounded hover:bg-blue-700 disabled:opacity-40">Lock</button>
            )}
          </div>
        </div>
      )}

      {record.audit_logs && record.audit_logs.length > 0 && (
        <div className="border-t pt-4">
          <div className="text-xs font-medium text-gray-500 mb-2">Audit trail</div>
          <div className="space-y-1.5">
            {record.audit_logs.map(log => (
              <div key={log.id} className="flex items-start gap-2 text-xs text-gray-600">
                <span className="text-gray-400 shrink-0">{new Date(log.timestamp).toLocaleString()}</span>
                <span className="font-medium text-gray-700">{log.action}</span>
                <span>by {log.actor}</span>
                {log.new_values?.flag_reason && <span className="text-red-600">— {String(log.new_values.flag_reason)}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Records() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [records, setRecords] = useState([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const { toasts, show: showToast, remove: removeToast } = useToast()

  const status = searchParams.get('status') || ''
  const scope = searchParams.get('scope') || ''
  const source_type = searchParams.get('source_type') || ''
  const search = searchParams.get('search') || ''

  const load = useCallback(() => {
    setLoading(true)
    const params = {}
    if (status) params.status = status
    if (scope) params.scope = scope
    if (source_type) params.source_type = source_type
    if (search) params.search = search
    api.records(params)
      .then(d => { setRecords(d.results); setCount(d.count) })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [status, scope, source_type, search])

  useEffect(() => { load() }, [load])

  async function openDetail(rec) {
    setDetailLoading(true)
    try {
      const full = await api.recordDetail(rec.id)
      setSelected(full)
    } finally {
      setDetailLoading(false)
    }
  }

  function setFilter(key, val) {
    const next = new URLSearchParams(searchParams)
    if (val) next.set(key, val)
    else next.delete(key)
    setSearchParams(next)
  }

  return (
    <>
    <div className="flex gap-6">
      <div className="flex-1 min-w-0 space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Activity Records</h1>
          <p className="text-sm text-gray-500">{count} records</p>
        </div>

        <div className="flex flex-wrap gap-2">
          <select value={status} onChange={e => setFilter('status', e.target.value)} className="border border-gray-300 rounded px-2 py-1.5 text-sm">
            <option value="">All statuses</option>
            {['PENDING','APPROVED','FLAGGED','REJECTED','LOCKED'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={scope} onChange={e => setFilter('scope', e.target.value)} className="border border-gray-300 rounded px-2 py-1.5 text-sm">
            <option value="">All scopes</option>
            <option value="1">Scope 1</option>
            <option value="2">Scope 2</option>
            <option value="3">Scope 3</option>
          </select>
          <select value={source_type} onChange={e => setFilter('source_type', e.target.value)} className="border border-gray-300 rounded px-2 py-1.5 text-sm">
            <option value="">All sources</option>
            {Object.entries(SOURCE_SHORT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input type="text" value={search} onChange={e => setFilter('search', e.target.value)} placeholder="Search description, location…" className="border border-gray-300 rounded px-2 py-1.5 text-sm flex-1 min-w-[180px]" />
        </div>

        {loading ? (
          <div className="text-gray-500 text-sm p-4">Loading…</div>
        ) : records.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-gray-400">No records match your filters.</div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Date</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Source</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Scope</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Description</th>
                  <th className="text-right px-4 py-2.5 text-xs font-medium text-gray-500">CO₂e (t)</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {records.map(r => (
                  <tr key={r.id} onClick={() => openDetail(r)} className={`cursor-pointer hover:bg-gray-50 transition-colors ${selected?.id === r.id ? 'bg-green-50' : ''}`}>
                    <td className="px-4 py-2.5 text-gray-500 whitespace-nowrap">{r.activity_date}</td>
                    <td className="px-4 py-2.5 whitespace-nowrap">{SOURCE_SHORT[r.source_type] || r.source_type}</td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${SCOPE_BADGE[r.scope] || ''}`}>S{r.scope}</span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 max-w-[200px] truncate">
                      {r.auto_flagged && <span className="text-red-400 mr-1" title="Auto-flagged">⚑</span>}
                      {r.description || r.location_label || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-right font-medium text-gray-900">
                      {r.co2e_kg ? (parseFloat(r.co2e_kg)/1000).toFixed(3) : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE[r.status] || ''}`}>{r.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {(selected || detailLoading) && (
        <div className="w-96 shrink-0">
          <div className="bg-white border border-gray-200 rounded-lg p-5 sticky top-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-800">Record detail</h2>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
            </div>
            {detailLoading ? (
              <div className="text-sm text-gray-500">Loading…</div>
            ) : selected ? (
              <RecordDetail
                record={selected}
                showToast={showToast}
                onAction={async () => {
                  load()
                  if (selected) {
                    const fresh = await api.recordDetail(selected.id)
                    setSelected(fresh)
                  }
                }}
              />
            ) : null}
          </div>
        </div>
      )}
    </div>
    <ToastContainer toasts={toasts} onClose={removeToast} />
    </>
  )
}
