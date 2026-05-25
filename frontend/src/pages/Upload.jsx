import { useState, useRef } from 'react'
import { api } from '../api/client'

const SOURCES = [
  {
    value: 'SAP_FUEL',
    label: 'SAP Fuel & Procurement',
    desc: 'Semicolon-delimited ME2N/MM60 export with German column headers',
    hint: 'Expected columns: Einkaufsbeleg, Werk, Buchungsdatum, Bestellmenge, Mengeneinheit, Materialgruppe',
  },
  {
    value: 'UTILITY_ELECTRICITY',
    label: 'Utility Electricity',
    desc: 'Portal CSV export from MSEDCL, BESCOM, TANGEDCO, BYPL or similar',
    hint: 'Expected columns: Account Number, Billing Period Start, Billing Period End, Total Usage (kWh)',
  },
  {
    value: 'TRAVEL',
    label: 'Corporate Travel (Concur)',
    desc: 'Concur expense report CSV with flights, hotels, and ground transport',
    hint: 'Expected columns: Expense Type, Transaction Date, Departure Airport Code, Arrival Airport Code, Nights',
  },
]

export default function Upload() {
  const [source, setSource] = useState('SAP_FUEL')
  const [file, setFile] = useState(null)
  const [actor, setActor] = useState('analyst')
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const fileRef = useRef(null)

  const selectedSource = SOURCES.find(s => s.value === source)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!file) return
    setUploading(true)
    setResult(null)
    setError('')
    try {
      const data = await api.ingest(source, file, actor)
      if (data.error) throw new Error(data.error)
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  function reset() {
    setResult(null)
    setFile(null)
    setError('')
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Upload Data</h1>
        <p className="text-sm text-gray-500 mt-0.5">Ingest a file from one of the three source types. The parser normalises units and computes CO₂e on upload.</p>
      </div>

      {result ? (
        <div className="bg-white border border-gray-200 rounded-lg p-6 space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <div className={`inline-flex items-center gap-1.5 text-sm font-medium px-3 py-1 rounded-full ${
                result.status === 'COMPLETE' ? 'bg-green-100 text-green-800'
                : result.status === 'PARTIAL' ? 'bg-yellow-100 text-yellow-800'
                : 'bg-red-100 text-red-800'
              }`}>
                {result.status}
              </div>
              <div className="font-medium text-gray-900 mt-2">{result.filename}</div>
            </div>
            <button onClick={reset} className="text-sm text-green-600 hover:underline">Upload another</button>
          </div>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="bg-gray-50 rounded p-3">
              <div className="text-2xl font-bold text-gray-900">{result.row_count}</div>
              <div className="text-xs text-gray-500">Rows read</div>
            </div>
            <div className="bg-green-50 rounded p-3">
              <div className="text-2xl font-bold text-green-700">{result.success_count}</div>
              <div className="text-xs text-gray-500">Imported</div>
            </div>
            <div className={`rounded p-3 ${result.error_count > 0 ? 'bg-red-50' : 'bg-gray-50'}`}>
              <div className={`text-2xl font-bold ${result.error_count > 0 ? 'text-red-600' : 'text-gray-400'}`}>{result.error_count}</div>
              <div className="text-xs text-gray-500">Errors / skipped</div>
            </div>
          </div>
          {result.parse_errors && result.parse_errors.length > 0 && (
            <div>
              <div className="text-sm font-medium text-gray-700 mb-2">Parse errors</div>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {result.parse_errors.map((e, i) => (
                  <div key={i} className="bg-red-50 border border-red-100 rounded p-3 text-xs">
                    <div className="font-medium text-red-700">Row {e.row_num}: {e.error}</div>
                    <div className="text-gray-500 mt-1 truncate">{JSON.stringify(e.raw)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-lg p-6 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Data source</label>
            <div className="space-y-2">
              {SOURCES.map(s => (
                <label key={s.value} className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  source === s.value ? 'border-green-500 bg-green-50' : 'border-gray-200 hover:border-gray-300'
                }`}>
                  <input type="radio" name="source" value={s.value} checked={source === s.value} onChange={() => setSource(s.value)} className="mt-0.5" />
                  <div>
                    <div className="text-sm font-medium text-gray-900">{s.label}</div>
                    <div className="text-xs text-gray-500 mt-0.5">{s.desc}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div className="bg-gray-50 rounded p-3 text-xs text-gray-500">
            <span className="font-medium text-gray-600">Expected format: </span>{selectedSource.hint}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">CSV file</label>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.txt"
              required
              onChange={e => setFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-gray-500 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-sm file:font-medium file:bg-green-50 file:text-green-700 hover:file:bg-green-100"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">Uploaded by</label>
            <input
              type="text"
              value={actor}
              onChange={e => setActor(e.target.value)}
              required
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
              placeholder="analyst name"
            />
          </div>

          {error && <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>}

          <button
            type="submit"
            disabled={uploading || !file}
            className="w-full bg-green-600 text-white py-2.5 rounded-md text-sm font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {uploading ? 'Uploading…' : 'Upload and parse'}
          </button>
        </form>
      )}
    </div>
  )
}
