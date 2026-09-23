import { useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { usePaged } from '../hooks/usePaged'
import { useResource } from '../hooks/useResource'
import { previewReverseOperation } from '../api/commands'
import { label } from '../utils/labels'
import { Button } from '../components/ui/Button'
export function History() {
  const page = usePaged('/operations?limit=30')
  return (
    <section className="page-stack">
      <h1>История операций</h1>
      {page.error && <p role="alert">{page.error.message}</p>}
      {page.items.map((operation) => (
        <Link className="card" to={`/operations/${operation.id}`} key={operation.id}>
          {label(operation.type || operation.command_type) || 'Операция учёта'} ·{' '}
          {new Date(operation.created_at).toLocaleString('ru-RU')} · {operation.status}
        </Link>
      ))}
      {page.loading && <p>Загрузка…</p>}
      {page.next_cursor && <Button onClick={page.more}>Загрузить ещё</Button>}
    </section>
  )
}
export function OperationDetail() {
  const { id } = useParams()
  const { data, error } = useResource(`/operations/${id}`)
  const [failure, setFailure] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  async function reverse() {
    setBusy(true)
    try {
      const review = await previewReverseOperation(id)
      navigate(`/review/${review.proposal_id}`)
    } catch (cause) {
      setFailure(cause.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="page-stack">
      <Link to="/history">← История</Link>
      <h1>Результат операции</h1>
      {(error || failure) && <p role="alert">{error?.message || failure}</p>}
      {data && (
        <>
          <p>
            {data.status} · {new Date(data.created_at).toLocaleString('ru-RU')}
          </p>
          {data.entries.map((entry) => (
            <div className="card" key={entry.id}>
              <strong>{entry.entity_type}</strong>
              {entry.entity_type === 'item' && (
                <Link to={`/items/${entry.entity_id}`}>Открыть вещь</Link>
              )}
              <div className="before-after">
                <pre>{JSON.stringify(entry.before_state ?? entry.before, null, 2)}</pre>
                <span>→</span>
                <pre>{JSON.stringify(entry.after_state ?? entry.after, null, 2)}</pre>
              </div>
            </div>
          ))}
          <Button variant="secondary" disabled={busy} onClick={reverse}>
            Предпросмотр отмены операции
          </Button>
        </>
      )}
    </section>
  )
}
