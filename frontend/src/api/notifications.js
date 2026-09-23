import { api } from './client'

export async function getNotifications(params = {}) {
  const query = new URLSearchParams()
  if (params.limit) query.append('limit', params.limit)
  if (params.cursor) query.append('cursor', params.cursor)

  const qs = query.toString()
  return api(`/notifications${qs ? `?${qs}` : ''}`)
}

export async function updateNotification(id, data) {
  return api(`/notifications/${id}`, {
    method: 'PATCH',
    body: data, // { expected_version, mark_read, dismiss }
  })
}

export async function snoozeNotification(id, data) {
  return api(`/notifications/${id}/snooze`, {
    method: 'POST',
    body: data, // { expected_version, hours }
  })
}

export async function getReminderRules(params = {}) {
  const query = new URLSearchParams()
  if (params.limit) query.append('limit', params.limit)
  if (params.cursor) query.append('cursor', params.cursor)

  const qs = query.toString()
  return api(`/reminder-rules${qs ? `?${qs}` : ''}`)
}

export async function createReminderRule(values) {
  return api(`/reminder-rules`, {
    method: 'POST',
    body: values, // { days_before, notification_type, location_ids, ... }
  })
}

export async function updateReminderRule(id, data) {
  return api(`/reminder-rules/${id}`, {
    method: 'PATCH',
    body: data, // { expected_version, values, enabled }
  })
}

export async function deleteReminderRule(id, expected_version) {
  return api(`/reminder-rules/${id}?expected_version=${expected_version}`, {
    method: 'DELETE',
  })
}
