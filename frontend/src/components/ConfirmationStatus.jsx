import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { checkConfirmation, onConfirmation, pendingConfirmations } from '../api/confirmations'
import { write } from '../api/client'
import { Button } from './ui/Button'

export function ConfirmationStatus() {
  const [rows, setRows] = useState(pendingConfirmations)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    let timer
    const unsubscribe = onConfirmation((receipt) => {
      if (active)
        setRows((previous) => [
          ...previous.filter((row) => row.confirmation_id !== receipt.confirmation_id),
          receipt,
        ])
    })
    async function poll() {
      try {
        for (const receipt of pendingConfirmations()) {
          if (active && !document.hidden) await checkConfirmation(receipt.confirmation_id)
        }
      } catch (cause) {
        if (active && cause.name !== 'AbortError') setError(cause.message)
      }
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
  return (
    <aside className="notice" aria-label="Сохранение операций" aria-live="polite">
      {rows.map((row) => (
        <div key={row.confirmation_id} className="toolbar">
          <span>
            {
              {
                queued: 'Подтверждено, ожидает сохранения',
                applying: 'Сохраняется',
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
