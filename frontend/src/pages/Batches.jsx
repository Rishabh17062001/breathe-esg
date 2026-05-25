import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

const STATUS_BADGE = {
  COMPLETE: 'bg-green-100 text-green-800',
  PARTIAL: 'bg-yellow-100 text-yellow-800',
  FAILED: 'bg-red-100 text-red-700',
  PROCESSING: 'bg-blue-100 text-blue-800',
}

const SOURCE_ICON = {
  SAP_FUEL: 'SAP',
  UTILITY_ELECTRICITY: 'Util',
  TRAVEL: 'Trvl',
}

export default function Batches() {
  const [batches, setBatches] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    api.batches().then(data => {
      setBatches(Array.isArray(data) ? data : (data.results || []))
    }).finally(() => setLoading(false))
  }, [])

  async function openDetail(b) {
    const detail = await api.batchDetail(b.id)
    setSelected(detail)
  }

  return (
    <div className="flex gap-6">
      <div className="flex-1 min-w-0 space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Ingestion Batches</h1>
          <p className="text-sm text-gray-500">{batches.length} uploads</p>
        </div>

        {loading ? (
          <div className="text-gray-500 text-sm p-4">Loading…</div>
        ) : batches.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-gray-400">
            No batches yet.{' '}
            <Link to="/upload" className="text-green-600 hover:underline">Upload a file</Link> to get started.
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">File</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Source</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Uploaded</th>
                  <th className="text-right px-4 py-2.5 text-xs font-medium text-gray-500">Rows</th>
                  <th className="text-right px-4 py-2.5 text-xs font-medium text-gray-500">OK / Err</th>
                  <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {batches.map(b => (
                  <tr
                    key={b.id}
                    onClick={() => openDetail(b)}
                    className={`cursor-pointer hover:bg-gray-50 transition-colors ${selected?.id === b.id ? 'bg-green-50' : ''}`}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-800 truncate max-w-[220px]">{b.filename}</div>
                      <div className="text-xs text-gray-400">{b.created_by}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-medium">
                        {SOURCE_ICON[b.source_type] || b.source_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                      {new Date(b.created_at).toLocaleDateString()}{' '}
                      <span className="text-gray-400">{new Date(b.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</span>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">{b.row_count}</td>
                    <td className="px-4 py-3 text-right">
                      <span className="text-green-700">{b.success_count}</span>
                      {' / '}
                      <span className={b.error_count > 0 ? 'text-red-600' : 'text-gray-400'}>{b.error_count}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE[b.status] || 'bg-gray-100 text-gray-600'}`}>
                        {b.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && (
        <div className="w-96 shrink-0">
          <div className="bg-white border border-gray-200 rounded-lg p-5 sticky top-4 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-800">Batch detail</h2>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
            </div>
            <div>
              <div className="font-medium text-gray-900 break-all">{selected.filename}</div>
              <div className="text-xs text-gray-500 mt-0.5">{selected.source_type_display}</div>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="bg-gray-50 rounded p-2">
                <div className="text-lg font-bold text-gray-900">{selected.row_count}</div>
                <div className="text-xs text-gray-500">Rows</div>
              </div>
              <div className="bg-green-50 rounded p-2">
                <div className="text-lg font-bold text-green-700">{selected.success_count}</div>
                <div className="text-xs text-gray-500">Imported</div>
              </div>
              <div className={`rounded p-2 ${selected.error_count > 0 ? 'bg-red-50' : 'bg-gray-50'}`}>
                <div className={`text-lg font-bold ${selected.error_count > 0 ? 'text-red-600' : 'text-gray-400'}`}>{selected.error_count}</div>
                <div className="text-xs text-gray-500">Errors</div>
              </div>
            </div>
            {selected.record_stats && Object.keys(selected.record_stats).length > 0 && (
              <div>
                <div className="text-xs font-medium text-gray-500 mb-2">Record status breakdown</div>
                <div className="space-y-1">
                  {Object.entries(selected.record_stats).map(([k, v]) => (
                    <div key={k} className="flex justify-between text-sm">
                      <span className="text-gray-600">{k}</span>
                      <span className="font-medium text-gray-900">{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <Link to={`/records?batch_id=${selected.id}`} className="block text-center text-sm text-green-600 hover:underline">
              View records from this batch →
            </Link>
            {selected.parse_errors && selected.parse_errors.length > 0 && (
              <div>
                <div className="text-xs font-medium text-gray-500 mb-2">Parse errors ({selected.parse_errors.length})</div>
                <div className="space-y-2 max-h-56 overflow-y-auto">
                  {selected.parse_errors.map((e, i) => (
                    <div key={i} className="bg-red-50 border border-red-100 rounded p-2 text-xs">
                      <div className="font-medium text-red-700">Row {e.row_num}: {e.error}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
