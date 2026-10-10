import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { checkConfirmation, onConfirmation, pendingConfirmations } from '../api/confirmations'
import { write } from '../api/client'
import { Button } from './ui/Button'

export function ConfirmationStatus() {
  const [rows, setRows] = useState(pendingConfirmations)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!rows.some((row) => row.status === 'applied')) return
    const timer = setTimeout(
      () => setRows((previous) => previous.filter((row) => row.status !== 'applied')),
      8000,
    )
    return () => clearTimeout(timer)
  }, [rows])
  useEffect(() => {
    let active = true
    let timer
    const unsubscribe = onConfirmation((receipt) => {
      if (active && receipt.status === 'unavailable')
        setRows((previous) =>
          previous.filter((row) => row.confirmation_id !== receipt.confirmation_id),
        )
      else if (active)
        setRows((previous) => [
          ...previous.filter(
            (row) => row.confirmation_id !== receipt.confirmation_id && row.status !== 'applied',
          ),
          receipt,
        ])
    })
    async function poll() {
      let failure = ''
      for (const receipt of pendingConfirmations()) {
        try {
          if (active && !document.hidden) await checkConfirmation(receipt.confirmation_id)
        } catch (cause) {
          if (cause.name !== 'AbortError') failure = cause.message
        }
      }
      if (active) setError(failure)
      if (active) timer = setTimeout(poll, 5000)
    }
    void poll()
    return () => {
      active = false
      clearTimeout(timer)
      unsubscribe()
    }
  }, [])
  if (!rows.length) return null
  const pending = rows.filter((row) => ['queued', 'applying'].includes(row.status))
  return (
    <aside className="notice" aria-label="Сохранение операций" aria-live="polite">
      {pending.length > 0 && (
        <p role="status">
          Сохраняем: {pending.length}. Можно продолжать работу; повторять добавление не нужно.
        </p>
      )}
      {rows
        .filter((row) => !['queued', 'applying'].includes(row.status))
        .map((row) => (
          <div key={row.confirmation_id} className="toolbar">
            <span>
              {
                {
                  applied: 'Сохранено',
                  conflict: 'Нужна повторная проверка',
                  failed: 'Сохранение не завершено',
                }[row.status]
              }
            </span>
            {row.status === 'applied' && (
              <Link to={`/operations/${row.operation_id}`}>Открыть операцию</Link>
            )}
            {row.status === 'conflict' && <Link to="/review">Проверить изменения</Link>}
            {row.status === 'failed' && (
              <Button
                variant="secondary"
                onClick={async () => {
                  try {
                    await write(`/confirmations/${row.confirmation_id}/retry`, {})
                    await checkConfirmation(row.confirmation_id)
                  } catch (cause) {
                    setError(cause.message)
                  }
                }}
              >
                Повторить сохранение
              </Button>
            )}
            {row.status === 'applied' && (
              <Button
                variant="text"
                onClick={() =>
                  setRows((previous) =>
                    previous.filter((r) => r.confirmation_id !== row.confirmation_id),
                  )
                }
              >
                Скрыть
              </Button>
            )}
          </div>
        ))}
      {error && <p role="alert">{error}</p>}
    </aside>
  )
}
