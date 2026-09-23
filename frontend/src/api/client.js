let accessToken = null
let workspaceId = null
let userId = null
let refreshPromise = null
let generation = 0
const requests = new Set()
const listeners = new Set()
const scopeListeners = new Set()
export const onScopeChanged = (callback) => {
  scopeListeners.add(callback)
  return () => scopeListeners.delete(callback)
}

export const getSession = () => ({ accessToken, workspaceId, userId, generation })
export const onSessionExpired = (listener) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function setSession(token, workspace, user) {
  if (
    (workspace !== undefined && workspace !== workspaceId) ||
    (user !== undefined && user !== userId)
  ) {
    generation++
    requests.forEach((controller) => controller.abort())
    if (workspace !== undefined) workspaceId = workspace
    if (user !== undefined) userId = user
    scopeListeners.forEach((callback) => callback())
  }
  if (token !== undefined) accessToken = token
}

export function clearSession() {
  generation++
  requests.forEach((controller) => controller.abort())
  accessToken = workspaceId = userId = null
  scopeListeners.forEach((callback) => callback())
}

export class ApiError extends Error {
  constructor(message, status, details = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    Object.assign(this, details)
  }
}

async function refresh() {
  const current = generation
  const run = async () => {
    if (generation !== current) throw new DOMException('Сессия изменена', 'AbortError')
    const response = await fetch('/api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_type: 'web' }),
    })
    if (generation !== current) throw new DOMException('Сессия изменена', 'AbortError')
    if (!response.ok) {
      if (response.status === 401) {
        clearSession()
        listeners.forEach((listener) => listener())
      }
      throw new ApiError('Не удалось восстановить сессию. Войдите повторно.', response.status)
    }
    const payload = await response.json()
    if (generation !== current) throw new DOMException('Сессия изменена', 'AbortError')
    accessToken = payload.access_token
    return accessToken
  }
  // Web Locks сериализует ротацию cookie между вкладками; токен остаётся в памяти.
  return navigator.locks ? navigator.locks.request('inventory-refresh', run) : run()
}

function refreshOnce() {
  refreshPromise ||= refresh().finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

export async function api(path, options = {}, retry = true) {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('://'))
    throw new Error('Недопустимый адрес API')
  const { body, key, blob, signal, ...rest } = options
  const current = generation
  const controller = new AbortController()
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) controller.abort()
  requests.add(controller)
  const method = (rest.method || 'GET').toUpperCase()
  const requestKey = key || (!['GET', 'HEAD'].includes(method) ? crypto.randomUUID() : undefined)
  const headers = new Headers(rest.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (workspaceId) headers.set('X-Workspace-ID', workspaceId)
  if (requestKey) headers.set('Idempotency-Key', requestKey)
  if (body !== undefined && !(body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  try {
    const response = await fetch(path.startsWith('/api/v1/') ? path : '/api/v1' + path, {
      ...rest,
      method,
      credentials: 'include',
      headers,
      signal: controller.signal,
      body: body instanceof FormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (generation !== current) throw new DOMException('Рабочая область изменена', 'AbortError')
    if (response.status === 401 && retry && !path.startsWith('/auth/')) {
      await refreshOnce()
      return api(path, { ...options, key: requestKey }, false)
    }
    if (!response.ok && response.status !== 304) {
      const payload = await response.json().catch(() => ({}))
      const error = payload.error || {}
      const fields = Array.isArray(error.field_errors)
        ? Object.fromEntries(
            error.field_errors.map((f, i) => [f.key || f.path || i, f.message || f.code]),
          )
        : error.field_errors
      throw new ApiError(
        error.message || `Запрос не выполнен (${response.status}).`,
        response.status,
        {
          details: error.details,
          fields,
          code: error.code,
          review: error.review || error.details?.review,
          requestId: error.request_id || response.headers.get('X-Request-ID'),
          retryAfter: response.headers.get('Retry-After'),
        },
      )
    }
    if (response.status === 204 || response.status === 304) return null
    const result = blob ? await response.blob() : await response.json()
    if (generation !== current || controller.signal.aborted)
      throw new DOMException('Сессия изменена', 'AbortError')
    return result
  } finally {
    requests.delete(controller)
    signal?.removeEventListener('abort', abort)
  }
}

export const write = (path, body, method = 'POST', key = crypto.randomUUID()) =>
  api(path, { method, body, key })
export async function restoreSession() {
  await refreshOnce()
  return api('/me')
}

export async function allPages(path, options) {
  const rows = []
  let cursor
  const seen = new Set()
  do {
    const result = await api(
      `${path}${path.includes('?') ? '&' : '?'}limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
      options,
    )
    rows.push(...result.items)
    cursor = result.next_cursor
    if (cursor && seen.has(cursor)) throw new Error('Сервер повторил курсор списка.')
    seen.add(cursor)
  } while (cursor)
  return rows
}
export const apiCall = api
