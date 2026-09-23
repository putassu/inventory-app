import { useState } from 'react'
import { Link } from 'react-router-dom'
import { usePaged } from '../hooks/usePaged'
import { useNotifications } from '../contexts/NotificationContext'
import { write } from '../api/client'
import { Button } from '../components/ui/Button'
export function Notifications() {
  const page = usePaged('/notifications?limit=30')
  const { refreshNotifications } = useNotifications()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(null)
  const [filter, setFilter] = useState('all')
  async function update(row, kind) {
    setBusy(row.id)
    setError('')
    try {
      await write(
        `/notifications/${row.id}${kind === 'snooze' ? '/snooze' : ''}`,
        {
          expected_version: row.version,
          ...(kind === 'snooze' ? { hours: 24 } : { [kind]: true }),
        },
        kind === 'snooze' ? 'POST' : 'PATCH',
      )
      page.reload()
      await refreshNotifications()
    } catch (cause) {
      setError(cause.message)
      if (cause.status === 409) page.reload()
    } finally {
      setBusy(null)
    }
  }
  return (
    <section className="page-stack">
      <h1>Уведомления</h1>
      <div className="toolbar">
        {['all', 'unread', 'read'].map((value) => (
          <Button
            key={value}
            variant={filter === value ? 'primary' : 'secondary'}
            onClick={() => setFilter(value)}
          >
            {{ all: 'Все загруженные', unread: 'Непрочитанные', read: 'Прочитанные' }[value]}
          </Button>
        ))}
      </div>
      {(error || page.error) && (
        <p role="alert" className="error">
          {error || page.error.message}
        </p>
      )}
      {page.items
        .filter((row) => filter === 'all' || (filter === 'read' ? !!row.read_at : !row.read_at))
        .map((row) => (
          <article className="card page-stack" key={row.id}>
            <h2>{row.reason || 'Напоминание о сроке'}</h2>
            <p>Срок: {row.due_date || 'Не указан'}</p>
            {row.item_id && <Link to={`/items/${row.item_id}`}>Открыть вещь</Link>}
            <div className="toolbar">
              {!row.read_at && (
                <Button disabled={!!busy} onClick={() => update(row, 'mark_read')}>
                  Прочитано
                </Button>
              )}
              <Button variant="secondary" disabled={!!busy} onClick={() => update(row, 'snooze')}>
                Отложить на день
              </Button>
              <Button variant="text" disabled={!!busy} onClick={() => update(row, 'dismiss')}>
                Скрыть
              </Button>
            </div>
          </article>
        ))}
      {page.loading && <p>Загрузка…</p>}
      {!page.loading && !page.error && !page.items.length && <p>Уведомлений пока нет.</p>}
      {page.has_more && (
        <Button disabled={page.loading} onClick={page.more}>
          Загрузить ещё
        </Button>
      )}
    </section>
  )
}
