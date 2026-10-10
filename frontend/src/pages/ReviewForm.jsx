import { randomId } from '../utils/id'
import { useEffect, useRef, useState } from 'react'
import { useParams, Link, useBlocker } from 'react-router-dom'
import { allPages, api, write } from '../api/client'
import { onConfirmation, submitConfirmation, waitForConfirmation } from '../api/confirmations'
import { ReviewField, supportedControls } from '../components/review/ReviewField'
import { ChangePreview } from '../components/review/ChangePreview'
import { Button } from '../components/ui/Button'
import { Modal } from '../components/ui/Modal'
import { Thumbnail } from '../components/ui/Thumbnail'
import { label } from '../utils/labels'
import {
  fieldValue,
  reviewFields,
  primaryField,
  reviewValue,
  activeWarnings,
} from '../utils/review'

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
  const [photo, setPhoto] = useState(null)
  const patchAttempt = useRef(null)
  const locked = useRef(false)
  useEffect(
    () =>
      onConfirmation((updated) => {
        if (updated.confirmation_id !== receipt?.confirmation_id) return
        setReceipt(updated)
        if (updated.status === 'applied') {
          setError('')
          setChanges({})
          setReview((previous) => ({ ...previous, status: 'applied' }))
        }
      }),
    [receipt?.confirmation_id],
  )
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
        if (document.confirmation) {
          setReceipt(document.confirmation)
          waitForConfirmation(document.confirmation)
            .then((result) => {
              if (!controller.signal.aborted) {
                setReceipt(result)
                setReview((previous) => ({ ...previous, status: 'applied' }))
              }
            })
            .catch((cause) => {
              if (!controller.signal.aborted && cause.name !== 'AbortError') {
                if (!cause.pending) setError(cause.message)
                if (cause.confirmation) setReceipt(cause.confirmation)
              }
            })
        }
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
    const result = Object.values(changes).map((change) => {
      const field = review.form.fields.find(
        (field) => field.action_id === change.action_id && field.key === change.key,
      )
      return {
        ...change,
        value: reviewValue(field, change.value),
      }
    })
    for (const action of review.actions) {
      const values = { ...action.values }
      for (const change of result)
        if (change.action_id === action.action_id) values[change.key] = change.value
      if (
        ['receive_stock', 'verify_item'].includes(action.type) &&
        values.item_mode === 'create' &&
        values.category === 'clothing' &&
        values.unit_code === 'pair' &&
        !values.attributes?.counting_unit &&
        !Object.hasOwn(values, 'attributes.counting_unit')
      )
        result.push({ action_id: action.action_id, key: 'attributes.counting_unit', value: 'pair' })
    }
    return result
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
          patchAttempt.current = { signature, key: randomId() }
        const updated = await write(
          `/proposals/${review.proposal_id}`,
          body,
          'PATCH',
          patchAttempt.current.key,
        )
        setReview(updated)
        setChanges({})
        setConflict(false)
        patchAttempt.current = null
      }
    } catch (cause) {
      if (cause.pending) setChanges({})
      else setError(cause.message)
      if (cause.confirmation) setReceipt(cause.confirmation)
      if (cause.review || cause.confirmation?.status === 'conflict') {
        const updated = cause.review || (await api(`/proposals/${review.proposal_id}`))
        setReview(updated)
        setConflict(cause.code !== 'REVIEW_VALIDATION_FAILED')
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
  const readonly =
    busy ||
    ['queued', 'applying'].includes(receipt?.status) ||
    (review && review.status !== 'editable')
  function changeField(action, field, value) {
    setError('')
    setChanges((previous) => {
      const next = { ...previous }
      const set = (key, value) => {
        next[`${action.action_id}:${key}`] = { action_id: action.action_id, key, value }
      }
      set(field.key, value)
      if (['receive_stock', 'verify_item'].includes(action.type) && field.key === 'tracking_mode') {
        const untracked = value === 'untracked'
        set('quantity_state', untracked ? 'not_applicable' : 'exact')
        set('quantity', untracked ? null : '1')
        set('unit_code', untracked ? null : 'pcs')
      }
      if (field.key === 'quantity_state' && ['unknown', 'not_applicable'].includes(value))
        set('quantity', null)
      if (field.key === 'item_id') set('lot_id', null)
      return next
    })
  }
  function renderField(action, field) {
    const key = `${field.action_id}:${field.key}`
    const current = fieldValue(action, field, {})
    const itemId = changes[`${action.action_id}:item_id`]?.value ?? action.values.item_id
    const scoped =
      action.type === 'receive_stock' && field.key === 'lot_id' && itemId
        ? { ...references, items: references.items.filter((item) => item.id === itemId) }
        : references
    return (
      <div key={key}>
        <ReviewField
          field={field}
          value={fieldValue(action, field, changes)}
          references={scoped}
          onChange={(value) => changeField(action, field, value)}
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
  }
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
              ? review.actions.some((action) => action.type === 'verify_item')
                ? 'Новые вещи уже в каталоге и участвуют в поиске и напоминаниях. Проверьте сведения, когда удобно.'
                : 'Изменение существующего учёта ожидает подтверждения'
              : label(review.status)}
          </p>
          {!!review.media?.length && (
            <div className="toolbar">
              {review.media.map((media, index) => (
                <Button
                  key={media.media_id}
                  variant="secondary"
                  aria-label={`Открыть фото источника ${index + 1}`}
                  onClick={() => setPhoto(media.media_id)}
                >
                  <Thumbnail mediaId={media.media_id} size={100} alt={`Фото ${index + 1}`} />
                </Button>
              ))}
            </div>
          )}
          <Modal isOpen={!!photo} title="Фото источника" onClose={() => setPhoto(null)}>
            {photo && <Thumbnail mediaId={photo} full alt="Фото источника" />}
          </Modal>
          {activeWarnings(review, changes).map((warning, index) => (
            <p key={index} className="notice">
              {typeof warning === 'string' ? warning : warning.message}
            </p>
          ))}
          {review.blocking_issues
            ?.filter((issue) => {
              const decision = review.required_decisions?.find(
                (d) => d.action_id === issue.action_id && d.code === issue.code,
              )
              return (
                !decision ||
                !decision.options.some(
                  (option) =>
                    option.value === changes[`${decision.action_id}:${decision.key}`]?.value,
                )
              )
            })
            .map((issue, index) => (
              <div key={index} className="notice">
                <p>{issue.message}</p>
                {issue.code === 'DUPLICATE_CANDIDATE' && (
                  <div className="actions">
                    <Button
                      disabled={readonly}
                      onClick={() =>
                        changeField(
                          review.actions.find((action) => action.action_id === issue.action_id),
                          { key: 'separate_item' },
                          true,
                        )
                      }
                    >
                      Это другая вещь — создать отдельно
                    </Button>
                    {issue.candidate_ids.map((itemId) => (
                      <Link key={itemId} className="btn btn-secondary" to={`/items/${itemId}`}>
                        Открыть имеющуюся вещь
                      </Link>
                    ))}
                  </div>
                )}
              </div>
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
          {review.actions.map((action, index) => {
            const fields = reviewFields(action, review.form?.fields || [], changes)
            const primary = fields.filter(primaryField)
            const secondary = fields.filter((field) => !primaryField(field))
            return (
              <fieldset
                key={action.action_id}
                disabled={readonly || unsupported}
                className="card page-stack"
              >
                <legend>
                  {review.actions.length > 1 ? `${index + 1}. ` : ''}
                  {label(action.type)}
                </legend>
                <div className="form-grid">
                  {primary.map((field) => renderField(action, field))}
                </div>
                {!!secondary.length && (
                  <details>
                    <summary>Дополнительные сведения</summary>
                    <div className="form-grid">
                      {secondary.map((field) => renderField(action, field))}
                    </div>
                  </details>
                )}
              </fieldset>
            )
          })}
          <details>
            <summary>Что изменится</summary>
            {review.actions.map((action) => (
              <div key={action.action_id}>
                <h3>{label(action.type)}</h3>
                {action.preview?.changes?.map((change, index) => (
                  <ChangePreview
                    key={index}
                    before={change.before}
                    after={change.after}
                    locations={references.locations}
                  />
                ))}
              </div>
            ))}
          </details>
          {receipt && (
            <p role="status">
              {
                {
                  applied: 'Сохранено',
                  queued: 'Сохраняем. Можно продолжать работу; повторять подтверждение не нужно.',
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
              {busy ? 'Сохраняем…' : 'Сохранить'}
            </Button>
            <Button
              variant="secondary"
              disabled={readonly || !dirty || unsupported}
              onClick={() => submit(false)}
            >
              Обновить предпросмотр
            </Button>
            {review.actions.some((action) => action.type === 'verify_item') ? (
              <Link to="/items">Проверить позже</Link>
            ) : (
              <Button variant="text" disabled={readonly} onClick={cancel}>
                Отменить предложение
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  )
}
