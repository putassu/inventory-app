import { useEffect, useRef, useState } from 'react'
import { useParams, Link, useBlocker } from 'react-router-dom'
import { allPages, api, write } from '../api/client'
import { submitConfirmation } from '../api/confirmations'
import { ReviewField, supportedControls } from '../components/review/ReviewField'
import { Button } from '../components/ui/Button'
import { Modal } from '../components/ui/Modal'
import { Thumbnail } from '../components/ui/Thumbnail'
import { normalizeDecimal } from '../utils/quantity'
import { label } from '../utils/labels'

export function ReviewForm() {
  const { id } = useParams()
  return <ReviewEditor key={id} id={id} />
}
function ReviewEditor({ id }) {
  const [review, setReview] = useState(null)
  const [references, setReferences] = useState({ locations: [], units: [], items: [], aliases: [] })
  const [changes, setChanges] = useState({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [receipt, setReceipt] = useState(null)
  const patchAttempt = useRef(null)
  const locked = useRef(false)
  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      let document
      try {
        document = await api(`/proposals/${id}`, { signal: controller.signal })
      } catch (cause) {
        if (cause.status !== 404) throw cause
        const task = await api(`/tasks/${id}`, { signal: controller.signal })
        if (!task.proposal_id) throw cause
        document = await api(`/proposals/${task.proposal_id}`, { signal: controller.signal })
      }
      const [locations, units, items] = await Promise.all([
        api('/locations', { signal: controller.signal }),
        api('/reference/units', { signal: controller.signal }),
        allPages('/items?include_archived=true', { signal: controller.signal }),
      ])
      const aliases = document.actions.some((action) => action.type === 'remove_alias')
        ? (
            await Promise.all(
              items.map((item) =>
                allPages(`/items/${item.id}/aliases`, { signal: controller.signal }),
              ),
            )
          ).flat()
        : []
      if (!controller.signal.aborted) {
        setReview(document)
        setReferences({ locations: locations.items, units: units.items, items, aliases })
      }
    }
    load().catch((cause) => {
      if (cause.name !== 'AbortError') setError(cause.message)
    })
    return () => controller.abort()
  }, [id])
  const dirty = Object.keys(changes).length > 0
  const blocker = useBlocker(dirty && !receipt)
  useEffect(() => {
    if (!dirty) return
    const warn = (event) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    const scopeChange = (event) => {
      if (!window.confirm('Есть несохранённые правки. Покинуть текущий инвентарь?'))
        event.preventDefault()
    }
    window.addEventListener('inventory:before-scope-change', scopeChange)
    return () => {
      window.removeEventListener('beforeunload', warn)
      window.removeEventListener('inventory:before-scope-change', scopeChange)
    }
  }, [dirty])
  const unsupported =
    review &&
    (review.schema_version !== 'review.v1' ||
      !review.form?.fields?.length ||
      review.form.fields.some((field) => !supportedControls.has(field.control)))
  function changeList() {
    return Object.values(changes).map((change) => {
      const field = review.form.fields.find(
        (field) => field.action_id === change.action_id && field.key === change.key,
      )
      return {
        ...change,
        value: ['number_stepper', 'decimal_input'].includes(field?.control)
          ? normalizeDecimal(change.value)
          : change.value,
      }
    })
  }
  async function submit(confirm) {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    setError('')
    try {
      const body = { expected_revision: review.revision, changes: changeList() }
      if (confirm) {
        const result = await submitConfirmation(`/proposals/${review.proposal_id}/confirm`, {
          ...body,
          observed_review_hash: review.review_hash,
        })
        setReceipt(result)
        setChanges({})
        setReview((previous) => ({ ...previous, status: 'applied' }))
      } else {
        const signature = JSON.stringify(body)
        if (patchAttempt.current?.signature !== signature)
          patchAttempt.current = { signature, key: crypto.randomUUID() }
        const updated = await write(
          `/proposals/${review.proposal_id}`,
          body,
          'PATCH',
          patchAttempt.current.key,
        )
        setReview(updated)
        setChanges({})
        patchAttempt.current = null
      }
    } catch (cause) {
      setError(cause.message)
      if (cause.confirmation) setReceipt(cause.confirmation)
      if (cause.review || cause.confirmation?.status === 'conflict') {
        const updated = cause.review || (await api(`/proposals/${review.proposal_id}`))
        setReview(updated)
        setConflict(true)
      }
    } finally {
      setBusy(false)
      locked.current = false
    }
  }
  async function cancel() {
    if (!window.confirm('Отменить это предложение? Подтверждённый учёт не изменится.')) return
    setBusy(true)
    try {
      setReview(await write(`/proposals/${review.proposal_id}/cancel`, {}))
      setChanges({})
    } catch (cause) {
      setError(cause.message)
    } finally {
      setBusy(false)
    }
  }
  const readonly = busy || (review && review.status !== 'editable')
  return (
    <section className="page-stack review-page">
      <Link to="/review">← Очередь проверки</Link>
      <h1>{review?.title || 'Проверка предложения'}</h1>
      {blocker.state === 'blocked' && (
        <Modal isOpen title="Есть несохранённые правки" onClose={() => blocker.reset()}>
          <p>Покинуть форму и потерять локальные изменения?</p>
          <div className="actions">
            <Button onClick={() => blocker.reset()}>Остаться</Button>
            <Button variant="danger" onClick={() => blocker.proceed()}>
              Покинуть форму
            </Button>
          </div>
        </Modal>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!review && !error && <p>Загрузка формы…</p>}
      {review && (
        <>
          <p>{review.summary}</p>
          <p className="notice">
            {label(review.effective_privacy)} ·{' '}
            {review.status === 'editable'
              ? 'Предложение ещё не сохранено в учёте'
              : label(review.status)}
          </p>
          {!!review.media?.length && (
            <div className="toolbar">
              {review.media.map((media) => (
                <Thumbnail
                  key={media.media_id}
                  mediaId={media.media_id}
                  size={100}
                  alt="Источник предложения"
                />
              ))}
            </div>
          )}
          {review.warnings?.map((warning, index) => (
            <p key={index} className="notice">
              {typeof warning === 'string' ? warning : warning.message}
            </p>
          ))}
          {review.blocking_issues?.map((issue, index) => (
            <p key={index} className="error">
              {issue.message}
            </p>
          ))}
          {unsupported && (
            <p role="alert" className="error">
              Версия формы или её поля не поддерживаются. Подтверждение отключено.
            </p>
          )}
          {conflict && (
            <div className="notice">
              <p>
                Сервер вернул актуальную форму. Ваши локальные правки сохранены; сравните их с
                текущими значениями.
              </p>
              <Button onClick={() => setConflict(false)}>Я проверил изменения</Button>
            </div>
          )}
          <fieldset disabled={readonly || unsupported} className="form-grid">
            {review.form?.fields?.map((field) => {
              const key = `${field.action_id}:${field.key}`
              const action = review.actions.find((action) => action.action_id === field.action_id)
              const current = Object.hasOwn(action?.values || {}, field.key)
                ? action.values[field.key]
                : field.value
              const value = changes[key] ? changes[key].value : current
              return (
                <div key={key}>
                  <ReviewField
                    field={field}
                    value={value}
                    references={references}
                    onChange={(value) =>
                      setChanges((previous) => ({
                        ...previous,
                        [key]: { action_id: field.action_id, key: field.key, value },
                      }))
                    }
                  />
                  {conflict && changes[key] && (
                    <small>
                      На сервере:{' '}
                      {typeof current === 'object'
                        ? JSON.stringify(current)
                        : String(current ?? 'Не указано')}
                    </small>
                  )}
                </div>
              )
            })}
          </fieldset>
          <details>
            <summary>Что изменится</summary>
            {review.actions.map((action) => (
              <div key={action.action_id}>
                <h3>{label(action.type)}</h3>
                {action.preview?.changes?.map((change, index) => (
                  <div className="before-after" key={index}>
                    <pre>{JSON.stringify(change.before, null, 2) || 'Новая запись'}</pre>
                    <span>→</span>
                    <pre>{JSON.stringify(change.after, null, 2) || 'Удаление'}</pre>
                  </div>
                ))}
              </div>
            ))}
          </details>
          {receipt && (
            <p role="status">
              {
                {
                  applied: 'Сохранено',
                  queued: 'Подтверждено, ожидает сохранения',
                  applying: 'Сохраняется',
                  failed: 'Сохранение не завершено',
                  conflict: 'Нужна повторная проверка',
                }[receipt.status]
              }{' '}
              {receipt.status === 'applied' && (
                <Link to={`/operations/${receipt.operation_id}`}>Открыть результат</Link>
              )}
            </p>
          )}
          <div className="toolbar">
            <Button
              disabled={readonly || unsupported || conflict || (!review.can_confirm && !dirty)}
              onClick={() => submit(true)}
            >
              {busy ? 'Ожидание сохранения…' : 'Подтвердить'}
            </Button>
            <Button
              variant="secondary"
              disabled={readonly || !dirty || unsupported}
              onClick={() => submit(false)}
            >
              Обновить предпросмотр
            </Button>
            <Button variant="text" disabled={readonly} onClick={cancel}>
              Отменить предложение
            </Button>
          </div>
        </>
      )}
    </section>
  )
}
