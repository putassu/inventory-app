import { Link, useNavigate } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { usePaged } from '../hooks/usePaged'
import { useTasks } from '../contexts/TaskContext'
import { api, write } from '../api/client'
import { waitForConfirmation } from '../api/confirmations'
import { Button } from '../components/ui/Button'
import { Modal } from '../components/ui/Modal'
import { supportedControls } from '../components/review/ReviewField'
export function ReviewInbox() {
  const page = usePaged('/review-inbox?limit=30'),
    { reload } = page
  const { activeTasks } = useTasks(),
    navigate = useNavigate()
  const [selected, setSelected] = useState(new Set()),
    [documents, setDocuments] = useState(null)
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [results, setResults] = useState([])
  const attempt = useRef(null)
  const version = activeTasks.reduce((sum, task) => sum + task.status_version, 0)
  useEffect(() => {
    reload()
  }, [version, reload])
  async function prepare(combine) {
    setBusy(true)
    setError('')
    try {
      const current = []
      for (const id of selected) current.push(await api(`/proposals/${id}`))
      if (combine) {
        const body = {
          sources: current.map((row) => ({ proposal_id: row.proposal_id, revision: row.revision })),
        }
        const signature = JSON.stringify(body)
        if (attempt.current?.signature !== signature)
          attempt.current = { signature, key: crypto.randomUUID() }
        const review = await write('/review-batches', body, 'POST', attempt.current.key)
        navigate(`/review/${review.proposal_id}`)
      } else {
        setDocuments(current)
        setResults([])
        attempt.current = {
          key: crypto.randomUUID(),
          body: {
            items: current.map((row) => ({
              proposal_id: row.proposal_id,
              expected_revision: row.revision,
              observed_review_hash: row.review_hash,
              changes: [],
              client_request_id: crypto.randomUUID(),
              idempotency_key: crypto.randomUUID(),
            })),
          },
        }
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  async function confirm() {
    setBusy(true)
    setError('')
    try {
      const result = await write(
        '/review-inbox/batch-confirm',
        attempt.current.body,
        'POST',
        attempt.current.key,
      )
      setResults(result.items)
      await Promise.all(
        result.items.map(async (row, i) => {
          if (!row.confirmation_id) return
          let next
          try {
            next = await waitForConfirmation(row)
          } catch (e) {
            next = e.confirmation || { ...row, error: { message: e.message } }
          }
          setResults((previous) => previous.map((value, index) => (index === i ? next : value)))
        }),
      )
      reload()
      setSelected(new Set())
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="page-stack">
      <div className="toolbar">
        <h1>Входящие на проверку</h1>
        <Button variant="secondary" onClick={reload}>
          Обновить
        </Button>
      </div>
      {(page.error || error) && (
        <p role="alert" className="error">
          {error || page.error.message}
        </p>
      )}
      {page.loading && <p>Загрузка…</p>}
      {selected.size > 0 && (
        <div className="notice actions">
          <span>Выбрано: {selected.size}</span>
          <Button
            disabled={busy || selected.size < 2 || selected.size > 50}
            onClick={() => prepare(true)}
          >
            Объединить для общей проверки
          </Button>
          <Button
            variant="secondary"
            disabled={busy || selected.size > 20}
            onClick={() => prepare(false)}
          >
            Проверить отдельно
          </Button>
        </div>
      )}
      {!page.loading && !page.error && !page.items.length && (
        <p>Нет предложений, требующих проверки.</p>
      )}
      {page.items.map((proposal) => (
        <article key={proposal.proposal_id} className="card toolbar">
          <input
            type="checkbox"
            disabled={busy}
            aria-label={`Выбрать: ${proposal.summary}`}
            checked={selected.has(proposal.proposal_id)}
            onChange={(event) =>
              setSelected((previous) => {
                const next = new Set(previous)
                if (event.target.checked) next.add(proposal.proposal_id)
                else next.delete(proposal.proposal_id)
                return next
              })
            }
          />
          <div>
            <h2>{proposal.summary}</h2>
            <small>{new Date(proposal.created_at).toLocaleString('ru-RU')}</small>
            {proposal.blocking_count > 0 && <p>Нужно уточнить: {proposal.blocking_count}</p>}
          </div>
          <Link className="btn btn-primary" to={`/review/${proposal.proposal_id}`}>
            Проверить
          </Link>
        </article>
      ))}
      {page.next_cursor && (
        <Button disabled={page.loading} onClick={page.more}>
          Загрузить ещё
        </Button>
      )}
      {documents && (
        <Modal
          isOpen
          busy={busy}
          title="Независимые подтверждения"
          onClose={() => {
            setDocuments(null)
            reload()
          }}
        >
          <div className="stack">
            <p>Каждое предложение сохраняется отдельно. Ошибка одного не отменяет остальные.</p>
            {documents.map((row, i) => (
              <section className="card" key={row.proposal_id}>
                <h3>{row.summary}</h3>
                <Link to={`/review/${row.proposal_id}`}>Открыть форму</Link>
                {!row.can_confirm && (
                  <p role="alert">Нужно уточнение. Откройте индивидуальную форму.</p>
                )}
                <details>
                  <summary>Все изменения</summary>
                  {row.actions.map((action) => (
                    <pre key={action.action_id}>
                      {JSON.stringify(action.preview || action.values, null, 2)}
                    </pre>
                  ))}
                </details>
                {results[i] && (
                  <p role="status">
                    {results[i].error?.message ||
                      {
                        applied: 'Сохранено',
                        queued: 'Принято, ожидает сохранения',
                        applying: 'Сохраняется',
                        failed: 'Ошибка сохранения',
                        conflict: 'Нужна повторная проверка',
                      }[results[i].status] ||
                      results[i].status}
                  </p>
                )}
              </section>
            ))}
            {error && <p role="alert">{error}</p>}
            <Button
              disabled={
                busy ||
                results.length > 0 ||
                documents.some(
                  (row) =>
                    !row.can_confirm ||
                    row.schema_version !== 'review.v1' ||
                    row.form?.fields.some((field) => !supportedControls.has(field.control)),
                )
              }
              onClick={confirm}
            >
              {busy ? 'Ожидание сохранения…' : 'Подтвердить каждое предложение'}
            </Button>
          </div>
        </Modal>
      )}
    </section>
  )
}
