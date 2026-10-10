import { useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { usePaged } from '../hooks/usePaged'
import { useResource } from '../hooks/useResource'
import { previewReverseOperation } from '../api/commands'
import { label } from '../utils/labels'
import { Button } from '../components/ui/Button'
import { ChangePreview } from '../components/review/ChangePreview'
export function History() {
  const page = usePaged('/operations?limit=30')
  return (
    <section className="page-stack">
      <div className="toolbar">
        <h1>История операций</h1>
        <Button variant="secondary" onClick={page.reload} disabled={page.loading}>
          Обновить
        </Button>
      </div>
      {page.error && <p role="alert">{page.error.message}</p>}
      {page.items.map((operation) => (
        <Link className="card" to={`/operations/${operation.id}`} key={operation.id}>
          {label(operation.type || operation.command_type) || 'Операция учёта'} ·{' '}
          {new Date(operation.created_at).toLocaleString('ru-RU')} · {label(operation.status)}
        </Link>
      ))}
      {page.loading && <p>Загрузка…</p>}
      {!page.loading && !page.error && !page.items.length && <p>Операций пока нет.</p>}
      {page.next_cursor && (
        <Button disabled={page.loading} onClick={page.more}>
          Загрузить ещё
        </Button>
      )}
    </section>
  )
}
export function OperationDetail() {
  const { id } = useParams()
  const { data, error } = useResource(`/operations/${id}`)
  const locations = useResource('/locations')
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
            {label(data.type)} · {label(data.status)} ·{' '}
            {new Date(data.created_at).toLocaleString('ru-RU')}
          </p>
          {data.entries.map((entry) => (
            <div className="card" key={entry.id}>
              <h2>{label(entry.entity_type)}</h2>
              {entry.entity_type === 'item' && (
                <Link to={`/items/${entry.entity_id}`}>Открыть вещь</Link>
              )}
              <ChangePreview
                before={entry.before_state ?? entry.before}
                after={entry.after_state ?? entry.after}
                locations={locations.data?.items}
              />
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
