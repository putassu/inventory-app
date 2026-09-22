let accessToken = null
let workspaceId = null
let refreshPromise = null

export function setSession(token, workspace) {
  if (token !== undefined) accessToken = token
  if (workspace !== undefined) workspaceId = workspace
}

async function refresh() {
  const response = await fetch('/api/v1/auth/refresh', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_type: 'web' }),
  })
  if (!response.ok) throw new Error('Войдите в приложение.')
  const data = await response.json()
  accessToken = data.access_token
}

export async function api(path, options = {}, retry = true) {
  const { body, key, blob, ...rest } = options
  const headers = { ...rest.headers }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  if (workspaceId) headers['X-Workspace-ID'] = workspaceId
  if (key) headers['Idempotency-Key'] = key
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch(path.startsWith('/api/v1/') ? path : '/api/v1' + path, {
    credentials: 'include',
    ...rest,
    headers,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  })
  if (
    response.status === 401 &&
    retry &&
    !['/auth/login', '/auth/refresh'].includes(path.replace(/^\/api\/v1/, ''))
  ) {
    refreshPromise ||= refresh().finally(() => {
      refreshPromise = null
    })
    await refreshPromise
    return api(path, options, false)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const error = new Error(payload.error?.message || 'Запрос не выполнен.')
    error.details = payload.error?.details
    error.fields = payload.error?.field_errors
    error.code = payload.error?.code
    throw error
  }
  if (blob) return response.blob()
  return response.status === 204 ? null : response.json()
}

export const write = (path, body, method = 'POST', key = crypto.randomUUID()) =>
  api(path, { method, body, key })

export async function restoreSession() {
  refreshPromise ||= refresh().finally(() => {
    refreshPromise = null
  })
  await refreshPromise
  return api('/me')
}

export async function allPages(path) {
  const rows = []
  let cursor = null
  do {
    const result = await api(
      path +
        (path.includes('?') ? '&' : '?') +
        'limit=100' +
        (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''),
    )
    rows.push(...result.items)
    cursor = result.next_cursor
  } while (cursor)
  return rows
}
