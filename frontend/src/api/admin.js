import { api } from './client'

// Settings
export async function getAdminSettingsSchema() {
  return api('/admin/settings/schema')
}

export async function getAdminSettings() {
  return api('/admin/settings')
}

export async function validateAdminSettings(patch) {
  return api('/admin/settings/validate', {
    method: 'POST',
    body: patch,
  })
}

export async function applyAdminSettings(patch) {
  return api('/admin/settings', {
    method: 'PATCH',
    body: patch,
  })
}

export async function getSettingsHistory() {
  return api('/admin/settings/history')
}

export async function rollbackSettings(rollback) {
  return api('/admin/settings/rollback', {
    method: 'POST',
    body: rollback,
  })
}

// Models
export async function getModels() {
  return api('/admin/models')
}

export async function updateModel(id, patch) {
  return api(`/admin/models/${id}`, {
    method: 'PATCH',
    body: patch,
  })
}

export async function healthCheckModel(id) {
  return api(`/admin/models/${id}/health-check`, {
    method: 'POST',
  })
}

// Queues & GPU
export async function getQueues() {
  return api('/admin/queues')
}

export async function queueAction(name, action) {
  return api(`/admin/queues/${name}/${action}`, {
    method: 'POST',
  })
}

export async function recoverGpu(data) {
  return api('/admin/gpu/recover', {
    method: 'POST',
    body: data,
  })
}

// Maintenance
export async function getAuditLogs(params = {}) {
  const query = new URLSearchParams()
  if (params.limit) query.append('limit', params.limit)
  if (params.cursor) query.append('cursor', params.cursor)

  const qs = query.toString()
  return api(`/admin/audit${qs ? `?${qs}` : ''}`)
}

export async function getMetrics() {
  return api('/admin/metrics')
}

export async function getHealth() {
  return api('/admin/health')
}

export async function reindexSearch() {
  return api('/admin/search/reindex', {
    method: 'POST',
  })
}

export async function gcPreview() {
  return api('/admin/gc/preview', {
    method: 'POST',
  })
}

export async function gcRun() {
  return api('/admin/gc/run', {
    method: 'POST',
  })
}

// Tasks Trace
export async function getTaskTrace(taskId) {
  return api(`/admin/tasks/${taskId}/trace`)
}

export async function replayTask(taskId) {
  return api(`/admin/tasks/${taskId}/replay`, {
    method: 'POST',
  })
}
