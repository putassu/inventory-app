import { useEffect, useState } from 'react'
import { allPages, api, write } from './api'

const labels = {
  create: 'Создать новую',
  existing: 'Выбрать существующую',
  exact: 'Точное',
  estimated: 'Оценка',
  unknown: 'Неизвестно',
  not_applicable: 'Без количественного учёта',
  counted: 'По количеству',
  measured: 'По мере',
  individual: 'Уникальный экземпляр',
  untracked: 'Только наличие',
  local_only: 'Только мой сервер',
  cloud_allowed: 'Разрешить внешний AI',
  day: 'День',
  month: 'Месяц',
  medicine: 'Лекарства',
  document: 'Документы',
  food: 'Продукты',
  clothing: 'Одежда',
  equipment: 'Техника',
  dishes: 'Посуда',
  cosmetics: 'Косметика',
  household: 'Быт',
  hobby: 'Хобби',
  other: 'Другое',
  place: 'Место',
  container: 'Контейнер',
  workspace: 'Вся рабочая область',
  user: 'Только я',
}

function Field({ field, value, onChange, references, loadAliases, aliasesBusy }) {
  const { key, control, label, options = [], editable } = field
  let choices = options.map((option) => ({
    ...option,
    label: labels[option.value] || option.label,
  }))
  if (control === 'location_picker')
    choices = references.locations.map((l) => ({ value: l.id, label: l.full_path }))
  if (key === 'unit_code')
    choices = references.units.map((u) => ({ value: u.code, label: u.display_name }))
  if (key === 'item_id') choices = references.items.map((i) => ({ value: i.id, label: i.name }))
  if (['lot_id', 'lot_ids'].includes(key))
    choices = references.items.flatMap((i) =>
      (i.lots || [])
        .filter((lot) => !lot.archived_at)
        .map((lot) => ({
          value: lot.id,
          label: `${i.name} · ${lot.label || lot.serial_number || 'Партия'} · срок ${lot.effective_expiry_on || 'неизвестен'}`,
        })),
    )
  if (key === 'alias_id')
    choices = references.aliases.map((alias) => ({
      value: alias.id,
      label: `${alias.item_name}: ${alias.alias}`,
    }))
  if (!editable)
    return (
      <div className="field">
        <span>{label}</span>
        <output>{JSON.stringify(value)}</output>
      </div>
    )
  if (control === 'switch' || control === 'checkbox')
    return (
      <label className="check">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    )
  if (choices.length || ['location_picker', 'entity_picker', 'unit_select'].includes(control)) {
    const multiple = key === 'lot_ids'
    return (
      <div>
        <label className="field">
          {label}
          <select
            multiple={multiple}
            value={value ?? (multiple ? [] : '')}
            onChange={(e) =>
              onChange(
                multiple
                  ? [...e.target.selectedOptions].map((o) => o.value)
                  : e.target.value || null,
              )
            }
          >
            {!multiple && <option value="">Не выбрано</option>}
            {choices.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        {key === 'alias_id' && references.aliasPages.length > 0 && (
          <button type="button" className="quiet" disabled={aliasesBusy} onClick={loadAliases}>
            Загрузить ещё названия
          </button>
        )}
      </div>
    )
  }
  const type =
    control === 'date_picker'
      ? 'date'
      : control === 'month_picker'
        ? 'month'
        : ['number_stepper', 'decimal_input'].includes(control) || field.value_type === 'integer'
          ? 'number'
          : 'text'
  return (
    <label className="field">
      {label}
      <input
        type={type}
        value={Array.isArray(value) ? value.join(', ') : (value ?? '')}
        step={field.validation?.step || 'any'}
        min={field.validation?.min}
        onChange={(e) =>
          onChange(
            control === 'chips_select'
              ? e.target.value
                  .split(',')
                  .map((v) => v.trim())
                  .filter(Boolean)
              : e.target.value === ''
                ? null
                : field.value_type === 'integer'
                  ? Number(e.target.value)
                  : e.target.value,
          )
        }
      />
    </label>
  )
}

function PrivatePhoto({ media }) {
  const [url, setUrl] = useState(null)
  useEffect(() => {
    let active = true
    let objectUrl
    api(media.download, { blob: true })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        if (active) setUrl(objectUrl)
        else URL.revokeObjectURL(objectUrl)
      })
      .catch(() => {})
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [media.download])
  return url ? <img src={url} alt="Исходная фотография для проверки" /> : null
}

export default function Review({ initial, onClose, onSaved }) {
  const [review, setReview] = useState(initial)
  const [changes, setChanges] = useState({})
  const [references, setReferences] = useState({
    locations: [],
    units: [],
    items: [],
    aliases: [],
    aliasPages: [],
  })
  const [aliasesBusy, setAliasesBusy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmation, setConfirmation] = useState(null)
  const [advanced, setAdvanced] = useState(false)
  const [submitKey, setSubmitKey] = useState(() => crypto.randomUUID())
  const [clientRequestId, setClientRequestId] = useState(() => crypto.randomUUID())
  const confirmationId = confirmation?.confirmation_id
  const confirmationStatus = confirmation?.status
  useEffect(() => {
    let active = true
    Promise.all([
      api('/locations'),
      api('/reference/units'),
      allPages('/items?include_archived=true'),
    ])
      .then(async ([locations, units, items]) => {
        const pages = initial.actions.some((a) => a.type === 'remove_alias')
          ? await Promise.all(
              items.map(async (item) => ({
                ...(await api(`/items/${item.id}/aliases`)),
                item_id: item.id,
                item_name: item.name,
              })),
            )
          : []
        const aliases = pages.flatMap((page) =>
          page.items.map((alias) => ({ ...alias, item_name: page.item_name })),
        )
        const aliasPages = pages.filter((page) => page.has_more && page.next_cursor)
        if (active)
          setReferences({
            locations: locations.items,
            units: units.items,
            items,
            aliases,
            aliasPages,
          })
      })
      .catch((e) => setError(e.message))
    return () => {
      active = false
    }
  }, [initial.actions])
  async function loadAliases() {
    setAliasesBusy(true)
    setError('')
    try {
      const pages = await Promise.all(
        references.aliasPages.map(async (page) => ({
          ...(await api(
            `/items/${page.item_id}/aliases?cursor=${encodeURIComponent(page.next_cursor)}`,
          )),
          item_id: page.item_id,
          item_name: page.item_name,
        })),
      )
      setReferences((old) => ({
        ...old,
        aliases: [
          ...old.aliases,
          ...pages.flatMap((page) =>
            page.items.map((alias) => ({ ...alias, item_name: page.item_name })),
          ),
        ],
        aliasPages: pages.filter((page) => page.has_more && page.next_cursor),
      }))
    } catch (e) {
      setError(e.message)
    } finally {
      setAliasesBusy(false)
    }
  }
  useEffect(() => {
    if (!confirmationId || !['queued', 'applying'].includes(confirmationStatus)) return
    let cancelled = false
    let timer
    async function poll() {
      if (document.hidden) {
        timer = setTimeout(poll, 3000)
        return
      }
      try {
        const result = await api('/confirmations/' + confirmationId)
        if (cancelled) return
        setConfirmation(result)
        if (result.status === 'applied') {
          onSaved()
          return
        }
        if (result.status === 'conflict') {
          setReview(await api('/proposals/' + review.proposal_id))
          setChanges({})
          setSubmitKey(crypto.randomUUID())
          setClientRequestId(crypto.randomUUID())
          setError('Данные изменились. Проверьте обновлённую форму.')
          return
        }
        if (result.status === 'failed') return
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
      if (!cancelled) timer = setTimeout(poll, 1500)
    }
    timer = setTimeout(poll, 1000)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [confirmationId, confirmationStatus, onSaved, review.proposal_id])
  const changeList = Object.values(changes)
  async function submit(confirm) {
    setBusy(true)
    setError('')
    try {
      if (confirm) {
        const result = await write(
          `/proposals/${review.proposal_id}/confirm`,
          {
            expected_revision: review.revision,
            observed_review_hash: review.review_hash,
            client_request_id: clientRequestId,
            changes: changeList,
          },
          'POST',
          submitKey,
        )
        setConfirmation(result)
      } else {
        setReview(
          await write(
            '/proposals/' + review.proposal_id,
            { expected_revision: review.revision, changes: changeList },
            'PATCH',
          ),
        )
        setChanges({})
        setSubmitKey(crypto.randomUUID())
        setClientRequestId(crypto.randomUUID())
      }
    } catch (e) {
      setError(e.message)
      if (e.details?.review) {
        setReview(e.details.review)
        setChanges({})
        setSubmitKey(crypto.randomUUID())
        setClientRequestId(crypto.randomUUID())
      }
    } finally {
      setBusy(false)
    }
  }
  const saving = confirmation && ['queued', 'applying', 'applied'].includes(confirmation.status)
  return (
    <section className="panel review" aria-label="Проверка предложения">
      <div className="heading">
        <div>
          <p className="eyebrow">Проверка перед сохранением</p>
          <h2>{review.title}</h2>
        </div>
        <button className="quiet" onClick={onClose}>
          Закрыть
        </button>
      </div>
      <p>{review.summary}</p>
      <div className="photos">
        {review.media?.map((media) => (
          <PrivatePhoto key={media.media_id} media={media} />
        ))}
      </div>
      {review.warnings?.map((warning, i) => (
        <p className="notice" key={i}>
          {warning}
        </p>
      ))}
      {review.blocking_issues?.map((issue, i) => (
        <p className="error" key={i}>
          {issue.message}
        </p>
      ))}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {confirmation && (
        <p role="status" className="notice">
          {
            {
              queued: 'Подтверждено, сохраняется…',
              applying: 'Подтверждено, сохраняется…',
              applied: 'Сохранено',
              conflict: 'Нужна повторная проверка',
              failed: 'Сохранение не завершено. Можно повторить это подтверждение.',
            }[confirmation.status]
          }
        </p>
      )}
      {!saving && review.status === 'editable' && (
        <>
          <div className="form-grid">
            {review.form?.fields
              .filter(
                (f) =>
                  advanced ||
                  f.importance === 'primary' ||
                  [
                    'unit_code',
                    'quantity_state',
                    'tracking_mode',
                    'expiry_on',
                    'to_location_id',
                    'name',
                    'category',
                    'primary_category',
                    'item_mode',
                    'item_id',
                    'parent_id',
                    'transfer_to_id',
                    'alias',
                    'alias_id',
                    'lot_ids',
                    'whole_presence',
                  ].includes(f.key),
              )
              .map((field) => {
                const action = review.actions.find((a) => a.action_id === field.action_id)
                const id = `${field.action_id}:${field.key}`
                return (
                  <Field
                    key={id}
                    field={field}
                    value={
                      id in changes
                        ? changes[id].value
                        : Object.hasOwn(action.values, field.key)
                          ? action.values[field.key]
                          : field.value
                    }
                    references={references}
                    loadAliases={loadAliases}
                    aliasesBusy={aliasesBusy}
                    onChange={(value) => {
                      setChanges((previous) => ({
                        ...previous,
                        [id]: { action_id: field.action_id, key: field.key, value },
                      }))
                      setSubmitKey(crypto.randomUUID())
                      setClientRequestId(crypto.randomUUID())
                    }}
                  />
                )
              })}
          </div>
          <button className="quiet" onClick={() => setAdvanced(!advanced)}>
            {advanced ? 'Меньше полей' : 'Все поля и свойства'}
          </button>
          <details>
            <summary>Что изменится</summary>
            {review.actions.map((action) => (
              <div key={action.action_id}>
                {action.preview?.changes?.map((change) => (
                  <p key={change.entity_id}>
                    {change.after?.name || change.after?.label || 'Остаток'}:{' '}
                    {change.before?.quantity ?? '—'} → {change.after?.quantity ?? 'без количества'}
                  </p>
                ))}
              </div>
            ))}
          </details>
          <div className="actions">
            <button
              disabled={busy || (!review.can_confirm && !changeList.length)}
              onClick={() => submit(true)}
            >
              {busy ? 'Сохраняем…' : 'Подтвердить'}
            </button>
            {!!changeList.length && (
              <button className="secondary" disabled={busy} onClick={() => submit(false)}>
                Обновить предпросмотр
              </button>
            )}
            <button
              className="quiet"
              disabled={busy}
              onClick={async () => {
                try {
                  await write(`/proposals/${review.proposal_id}/cancel`, {})
                  onClose()
                } catch (e) {
                  setError(e.message)
                }
              }}
            >
              Отменить предложение
            </button>
          </div>
        </>
      )}
      {confirmation?.status === 'failed' && (
        <button
          onClick={async () => {
            try {
              setConfirmation(
                await write(`/confirmations/${confirmation.confirmation_id}/retry`, {}),
              )
            } catch (e) {
              setError(e.message)
            }
          }}
        >
          Повторить сохранение
        </button>
      )}
    </section>
  )
}
