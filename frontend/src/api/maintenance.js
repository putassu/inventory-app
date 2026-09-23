import { api } from './client'

export async function startExport(data) {
  return api('/exports', {
    method: 'POST',
    body: data, // { format, include_media, include_history }
  })
}

export async function getExportStatus(id) {
  return api(`/exports/${id}`)
}

export function getExportDownloadUrl(id) {
  // Using the API proxy path setup in vite.config.js
  return `/api/v1/exports/${id}/download`
}

export async function createDeletionPreview(item_ids) {
  return api('/deletion-previews', {
    method: 'POST',
    body: { item_ids },
  })
}

export async function confirmPurge(data) {
  return api('/purge-jobs', {
    method: 'POST',
    body: data, // { preview_id, preview_revision, preview_hash, explicit_confirmation }
  })
}

export async function getPurgeJobs(params = {}) {
  const query = new URLSearchParams()
  if (params.limit) query.append('limit', params.limit)
  if (params.cursor) query.append('cursor', params.cursor)

  const qs = query.toString()
  return api(`/purge-jobs${qs ? `?${qs}` : ''}`)
}

export async function getPurgeJobStatus(id) {
  return api(`/purge-jobs/${id}`)
}

export async function cancelPurgeJob(id, expected_version) {
  return api(`/purge-jobs/${id}/cancel`, {
    method: 'POST',
    body: { expected_version, explicit_confirmation: true },
  })
}
