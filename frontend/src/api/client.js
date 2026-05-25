const BASE = '/api/v1'

async function req(path, opts = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}

export const api = {
  dashboard: () => req('/dashboard/'),
  clients: () => req('/clients/'),

  records: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return req(`/records/${qs ? '?' + qs : ''}`)
  },
  recordDetail: (id) => req(`/records/${id}/`),
  recordAction: (id, action, actor, reason = '') =>
    req(`/records/${id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ action, actor, reason }),
    }),
  bulkAction: (ids, action, actor, reason = '') =>
    req('/records/bulk/', {
      method: 'POST',
      body: JSON.stringify({ ids, action, actor, reason }),
    }),

  batches: () => req('/batches/'),
  batchDetail: (id) => req(`/batches/${id}/`),

  ingest: async (sourceType, file, actor) => {
    const form = new FormData()
    form.append('file', file)
    form.append('created_by', actor)
    const r = await fetch(`${BASE}/ingest/${sourceType}/`, { method: 'POST', body: form })
    return r.json()
  },
}
