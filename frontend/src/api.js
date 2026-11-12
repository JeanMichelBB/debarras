const BASE = (import.meta.env?.VITE_API_URL || 'http://localhost:8002').replace(/\/$/, '')
const TOKEN_KEY = 'debarras_token'
// Dev only: add ?slow to the address to wait 1 second before every API call, so loading states stay visible.
const SLOW_MS = import.meta.env.DEV && new URLSearchParams(window.location.search).has('slow') ? 1000 : 0

export class ApiError extends Error {
  constructor(status, message, code) {
    super(message)
    this.status = status
    this.code = code // 'network' | 'session' | 'rate' | undefined
  }
}

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY))

let onUnauthorized = () => {}
export const setOnUnauthorized = (fn) => {
  onUnauthorized = fn
}

/** FastAPI returns detail as a string, or a list of validation errors. */
export function detailMessage(detail, fallback) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) return detail.map((d) => d.msg).join('; ')
  return fallback
}

async function request(path, { method = 'GET', body, form, query, auth = true, raw = false } = {}) {
  const url = new URL(BASE + path)
  if (query) for (const [k, v] of Object.entries(query)) if (v !== '' && v != null) url.searchParams.set(k, v)
  const headers = {}
  const token = getToken()
  if (auth && token) headers.Authorization = `Bearer ${token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  if (SLOW_MS) await new Promise((r) => setTimeout(r, SLOW_MS))
  let res
  try {
    res = await fetch(url, { method, headers, body: payload })
  } catch {
    throw new ApiError(0, 'network', 'network')
  }
  if (res.status === 401 && auth && token) {
    onUnauthorized()
    throw new ApiError(401, 'session', 'session')
  }
  if (!res.ok) {
    let detail
    try {
      detail = (await res.json()).detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detailMessage(detail, `HTTP ${res.status}`), res.status === 429 ? 'rate' : undefined)
  }
  if (raw) return res
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  // auth
  registerBegin: (display_name) => request('/auth/register/begin', { method: 'POST', body: display_name ? { display_name } : {}, auth: false }),
  registerFinish: (credential, state) => request('/auth/register/finish', { method: 'POST', body: { credential, state }, auth: false }),
  loginBegin: () => request('/auth/login/begin', { method: 'POST', auth: false }),
  loginFinish: (credential, state) => request('/auth/login/finish', { method: 'POST', body: { credential, state }, auth: false }),
  recover: (code) => request('/auth/recover', { method: 'POST', body: { code }, auth: false }),
  // account
  me: () => request('/me'),
  updateMe: (patch) => request('/me', { method: 'PATCH', body: patch }),
  deleteAccount: () => request('/me', { method: 'DELETE' }),
  newRecoveryCodes: () => request('/me/recovery-codes', { method: 'POST' }),
  passkeys: () => request('/me/passkeys'),
  addPasskeyBegin: () => request('/me/passkeys/begin', { method: 'POST' }),
  addPasskeyFinish: (credential, state) => request('/me/passkeys/finish', { method: 'POST', body: { credential, state } }),
  deletePasskey: (id) => request(`/me/passkeys/${id}`, { method: 'DELETE' }),
  // titles
  queue: (params) => request('/titles/queue', { query: params }),
  details: (mt, id) => request(`/titles/${mt}/${id}`),
  facts: (mt, id) => request(`/titles/${mt}/${id}/facts`),
  genres: () => request('/meta/genres'),
  loginPosters: () => request('/public/login-posters', { auth: false }),
  person: (id) => request(`/people/${id}`),
  company: (id) => request(`/companies/${id}`),
  // swipes
  swipe: (body) => request('/swipe', { method: 'POST', body }),
  undo: (mt, id) => request(`/swipe/${mt}/${id}`, { method: 'DELETE' }),
  swipes: (params) => request('/swipes', { query: params }),
  stats: () => request('/swipes/stats'),
  // import / export
  startImport: (file, status) => {
    const form = new FormData()
    form.append('file', file)
    form.append('status', status)
    return request('/import', { method: 'POST', form })
  },
  importStatus: (id) => request(`/import/${id}`),
  exportCsv: async (status) => {
    const res = await request(`/export/${status}`, { raw: true })
    return { blob: await res.blob(), missing: Number(res.headers.get('X-Missing-Imdb') || 0) }
  },
}
