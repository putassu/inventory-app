import { api } from './client'

export async function getInbox(params = {}) {
  const query = new URLSearchParams()
  if (params.limit) query.append('limit', params.limit)
  if (params.cursor) query.append('cursor', params.cursor)
  if (params.batch_id) query.append('batch_id', params.batch_id)

  const qs = query.toString()
  return api(`/review-inbox${qs ? `?${qs}` : ''}`)
}

export async function getProposal(id) {
  return api(`/proposals/${id}`)
}

export async function patchProposal(id, data) {
  return api(`/proposals/${id}`, {
    method: 'PATCH',
    body: data, // { expected_revision, changes: [...] }
  })
}

export async function confirmProposal(id, data) {
  return api(`/proposals/${id}/confirm`, {
    method: 'POST',
    body: data, // { expected_revision, observed_review_hash, client_request_id, changes }
  })
}

export async function cancelProposal(id) {
  return api(`/proposals/${id}/cancel`, {
    method: 'POST',
    body: {},
  })
}
