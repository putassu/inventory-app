import { randomId } from '../utils/id'
import { api, getSession, write, onScopeChanged } from './client'

const attempts = new Map()
const observed = new Map()
onScopeChanged(() => {
  attempts.clear()
  observed.clear()
})
const observers = new Set()
export const onConfirmation = (callback) => {
  observers.add(callback)
  return () => observers.delete(callback)
}
const scopeKey = () => `inventory-confirmations:${getSession().userId}:${getSession().workspaceId}`
export function pendingConfirmations() {
  try {
    return JSON.parse(sessionStorage.getItem(scopeKey()) || '[]')
  } catch {
    return []
  }
}
function remember(receipt) {
  if (!receipt.confirmation_id) return
  const previous = pendingConfirmations()
  const changed = observed.get(receipt.confirmation_id) !== receipt.status
  observed.set(receipt.confirmation_id, receipt.status)
  if (receipt.status === 'applied') {
    for (const [identity, attempt] of attempts) {
      if (attempt.receipt?.confirmation_id === receipt.confirmation_id) attempts.delete(identity)
    }
  }
  const rows = previous.filter((row) => row.confirmation_id !== receipt.confirmation_id)
  if (receipt.status !== 'applied')
    rows.push({ confirmation_id: receipt.confirmation_id, status: receipt.status })
  sessionStorage.setItem(scopeKey(), JSON.stringify(rows))
  if (changed) observers.forEach((callback) => callback(receipt))
}
export async function waitForConfirmation(receipt, timeout = 45000) {
  const scope = getSession().generation
  remember(receipt)
  const deadline = Date.now() + timeout
  while (['queued', 'applying'].includes(receipt.status)) {
    if (Date.now() > deadline) {
      const error = new Error(
        'Подтверждение принято и ещё сохраняется. Следите за ним в блоке сохранения; повтор не создаст новую операцию.',
      )
      error.confirmation = receipt
      error.pending = true
      throw error
    }
    await new Promise((resolve) =>
      setTimeout(resolve, Math.max(500, receipt.poll_after_ms || 1000)),
    )
    if (scope !== getSession().generation)
      throw new DOMException('Рабочая область изменена', 'AbortError')
    receipt = await api(`/confirmations/${receipt.confirmation_id}`)
    remember(receipt)
  }
  if (receipt.status !== 'applied') {
    const error = new Error(
      receipt.status === 'conflict'
        ? 'Учёт изменился. Проверьте актуальную форму и подтвердите заново.'
        : 'Сохранение не завершено. Повторите принятое подтверждение в блоке сохранения.',
    )
    error.confirmation = receipt
    error.code = receipt.error_code
    throw error
  }
  return receipt
}

// Одна неизменная попытка на тело запроса. Сетевой повтор получает тот же ключ и receipt.
export async function submitConfirmation(path, body) {
  const { generation } = getSession()
  const identity = JSON.stringify([generation, path, body])
  let attempt = attempts.get(identity)
  if (!attempt) {
    attempt = {
      key: randomId(),
      body: { ...body, client_request_id: body.client_request_id || randomId() },
    }
    attempts.set(identity, attempt)
  }
  if (!attempt.promise) {
    attempt.promise = (async () => {
      try {
        attempt.receipt ||= await write(path, attempt.body, 'POST', attempt.key)
        const result = await waitForConfirmation(
          attempt.receipt,
          path === '/commands/manual-confirm' ? 10000 : 45000,
        )
        attempts.delete(identity)
        return result
      } catch (error) {
        if ((error.status && error.status < 500) || error.confirmation?.status === 'conflict')
          attempts.delete(identity)
        throw error
      } finally {
        attempt.promise = null
      }
    })()
  }
  return attempt.promise
}

export async function checkConfirmation(id) {
  try {
    const receipt = await api(`/confirmations/${id}`)
    remember(receipt)
    return receipt
  } catch (error) {
    if (![404, 410].includes(error.status)) throw error
    // После явной очистки стенда старые локальные receipt больше не существуют.
    sessionStorage.setItem(
      scopeKey(),
      JSON.stringify(pendingConfirmations().filter((row) => row.confirmation_id !== id)),
    )
    observed.delete(id)
    observers.forEach((callback) => callback({ confirmation_id: id, status: 'unavailable' }))
    return null
  }
}
