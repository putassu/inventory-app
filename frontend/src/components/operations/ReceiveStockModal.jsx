import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { receiveStock } from '../../api/commands'
import { normalizeDecimal } from '../../utils/quantity'
import { useResource } from '../../hooks/useResource'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { ReviewField } from '../review/ReviewField'

export function ReceiveStockModal(props) {
  return props.isOpen ? <ReceiveForm {...props} /> : null
}
function ReceiveForm({ onClose, onSuccess, item = null, locations = [] }) {
  const [values, setValues] = useState({
    item_name: item?.name || '',
    category: item?.primary_category || 'other',
    tracking_mode: item?.tracking_mode || 'counted',
    unit_code: item?.base_unit_id || 'pcs',
    quantity: '1',
    quantity_state: item?.tracking_mode === 'untracked' ? 'not_applicable' : 'exact',
    quantity_step: String(item?.quantity_step || '1'),
    location_id: '',
    lot_mode: 'create',
    attributes: {},
    privacy_policy: item?.privacy_policy || 'local_only',
  })
  const [fields, setFields] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submitting = useRef(false)
  const navigate = useNavigate()
  const { data: units } = useResource('/reference/units')
  const { data: categories } = useResource('/reference/categories')
  useEffect(() => {
    const controller = new AbortController()
    api(`/forms?operation=receive_stock&category=${values.category}`, { signal: controller.signal })
      .then((data) => setFields(data.fields))
      .catch((cause) => {
        if (cause.name !== 'AbortError') setError(cause.message)
      })
    return () => controller.abort()
  }, [values.category])
  const set = (key, value) => setValues((previous) => ({ ...previous, [key]: value }))
  function attribute(field, value) {
    const path = field.key.split('.').slice(1)
    setValues((previous) => {
      const attributes = structuredClone(previous.attributes)
      if (path.length === 2)
        attributes[path[0]] = { ...(attributes[path[0]] || {}), [path[1]]: value }
      else if (value === null) delete attributes[path[0]]
      else attributes[path[0]] = value
      return { ...previous, attributes }
    })
  }
  async function submit(event) {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true
    setBusy(true)
    setError('')
    try {
      if (!item && !values.item_name.trim()) throw new Error('Укажите название вещи.')
      const untracked = values.tracking_mode === 'untracked'
      const quantityState = untracked ? 'not_applicable' : values.quantity_state
      const quantity = ['unknown', 'not_applicable'].includes(quantityState)
        ? null
        : normalizeDecimal(values.quantity)
      if (['exact', 'estimated'].includes(quantityState) && quantity === null)
        throw new Error('Укажите количество или выберите «Неизвестно».')
      const attributes = { ...values.attributes }
      if (values.category === 'clothing' && values.unit_code === 'pair')
        attributes.counting_unit = 'pair'
      const body = {
        ...values,
        attributes,
        item_mode: item ? 'existing' : 'create',
        item_id: item?.id,
        location_id: values.location_id || null,
        unit_code: untracked ? null : values.unit_code,
        quantity,
        quantity_state: quantityState,
        quantity_step: normalizeDecimal(values.quantity_step),
        privacy_policy: values.category === 'document' ? 'local_only' : values.privacy_policy,
      }
      if (body.expiry_on && body.expiry_precision === 'month' && body.expiry_on.length === 7)
        body.expiry_on += '-01'
      if (!body.expiry_on) body.expiry_precision = 'unknown'
      const result = await receiveStock(body, item ? { [`item:${item.id}`]: item.version } : {})
      onSuccess?.(result)
      onClose()
    } catch (cause) {
      if (cause.review?.proposal_id) {
        onClose()
        navigate(`/review/${cause.review.proposal_id}`)
      } else setError(cause.message)
    } finally {
      setBusy(false)
      submitting.current = false
    }
  }
  const optional = fields.filter(
    (field) =>
      !field.key.startsWith('attributes.') &&
      [
        'brand',
        'model',
        'barcode',
        'user_description',
        'tags',
        'label',
        'serial_number',
        'manufacturer_batch',
        'acquired_at',
        'manufactured_on',
        'opened_on',
        'after_opening_amount',
        'after_opening_unit',
        'package_size',
        'privacy_policy',
      ].includes(field.key),
  )
  const reference = { locations, units: units?.items || [], items: item ? [item] : [] }
  return (
    <Modal
      isOpen
      busy={busy}
      onClose={onClose}
      title={item ? `Поступление: ${item.name}` : 'Поступление вручную'}
    >
      <form className="page-stack" onSubmit={submit}>
        <fieldset disabled={busy} className="page-stack">
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {!item && (
            <>
              <Input
                label="Название вещи"
                required
                value={values.item_name}
                onChange={(event) => set('item_name', event.target.value)}
              />
              <Select
                label="Категория"
                value={values.category}
                onChange={(event) =>
                  setValues((previous) => ({
                    ...previous,
                    category: event.target.value,
                    attributes: {},
                    privacy_policy:
                      event.target.value === 'document' ? 'local_only' : previous.privacy_policy,
                  }))
                }
              >
                {categories?.items.map((category) => (
                  <option key={category.code} value={category.code}>
                    {category.name}
                  </option>
                ))}
              </Select>
              <Select
                label="Режим учёта"
                value={values.tracking_mode}
                onChange={(event) =>
                  setValues((previous) => ({
                    ...previous,
                    tracking_mode: event.target.value,
                    quantity_state: event.target.value === 'untracked' ? 'not_applicable' : 'exact',
                  }))
                }
              >
                <option value="counted">По количеству</option>
                <option value="measured">По мере</option>
                <option value="individual">Уникальный экземпляр</option>
                <option value="untracked">Только наличие</option>
              </Select>
            </>
          )}
          {values.tracking_mode !== 'untracked' && (
            <>
              <Select
                label="Единица"
                value={values.unit_code}
                onChange={(event) => set('unit_code', event.target.value)}
              >
                {units?.items.map((unit) => (
                  <option key={unit.code} value={unit.code}>
                    {unit.display_name}
                  </option>
                ))}
              </Select>
              <Select
                label="Точность количества"
                value={values.quantity_state}
                onChange={(event) => set('quantity_state', event.target.value)}
              >
                <option value="exact">Точное</option>
                <option value="estimated">Примерное</option>
                <option value="unknown">Неизвестно</option>
              </Select>
              {values.quantity_state !== 'unknown' && (
                <Input
                  label="Количество"
                  required
                  inputMode="decimal"
                  value={values.quantity}
                  onChange={(event) => set('quantity', event.target.value)}
                />
              )}
              {!item && (
                <Input
                  label="Шаг базового количества"
                  value={values.quantity_step}
                  inputMode="decimal"
                  onChange={(event) => set('quantity_step', event.target.value)}
                />
              )}
            </>
          )}
          <Select
            label="Место хранения"
            value={values.location_id}
            onChange={(event) => set('location_id', event.target.value)}
          >
            <option value="">Место не указано</option>
            {locations.map((location) => (
              <option key={location.id} value={location.id}>
                {location.full_path}
              </option>
            ))}
          </Select>
          {item && (
            <>
              <Select
                label="Партия"
                value={values.lot_mode}
                onChange={(event) => set('lot_mode', event.target.value)}
              >
                <option value="create">Новая партия</option>
                <option value="existing">Существующая партия</option>
              </Select>
              {values.lot_mode === 'existing' && (
                <Select
                  label="Выберите партию"
                  required
                  value={values.lot_id || ''}
                  onChange={(event) => set('lot_id', event.target.value)}
                >
                  <option value="">Выберите</option>
                  {item.lots
                    .filter((lot) => !lot.archived_at)
                    .map((lot) => (
                      <option key={lot.id} value={lot.id}>
                        {lot.label || lot.serial_number || lot.id.slice(0, 8)}
                      </option>
                    ))}
                </Select>
              )}
            </>
          )}
          {values.lot_mode === 'create' && (
            <>
              <Select
                label="Точность срока годности"
                value={values.expiry_precision || 'unknown'}
                onChange={(event) => {
                  set('expiry_precision', event.target.value)
                  set('expiry_on', null)
                }}
              >
                <option value="unknown">Неизвестно</option>
                <option value="day">День</option>
                <option value="month">Месяц</option>
              </Select>
              {['day', 'month'].includes(values.expiry_precision) && (
                <Input
                  type={values.expiry_precision === 'month' ? 'month' : 'date'}
                  label="Годен до"
                  value={values.expiry_on || ''}
                  onChange={(event) => set('expiry_on', event.target.value)}
                />
              )}
            </>
          )}
          {!item &&
            fields
              .filter((field) => field.key.startsWith('attributes.'))
              .map((field) => {
                const value = field.key
                  .split('.')
                  .slice(1)
                  .reduce((current, key) => current?.[key], values.attributes)
                return (
                  <ReviewField
                    key={field.key}
                    field={field}
                    value={value}
                    references={reference}
                    onChange={(value) => attribute(field, value)}
                  />
                )
              })}
          <details>
            <summary>Дополнительно</summary>
            <div className="page-stack">
              {optional
                .filter(
                  (field) =>
                    !(
                      item &&
                      [
                        'brand',
                        'model',
                        'barcode',
                        'user_description',
                        'tags',
                        'privacy_policy',
                      ].includes(field.key)
                    ),
                )
                .map((field) => (
                  <ReviewField
                    key={field.key}
                    field={{
                      ...field,
                      editable: !(field.key === 'privacy_policy' && values.category === 'document'),
                    }}
                    references={reference}
                    value={values[field.key] ?? field.value}
                    onChange={(value) => set(field.key, value)}
                  />
                ))}
            </div>
          </details>
          <Button type="submit" disabled={busy}>
            {busy ? 'Подтверждено, ожидаем сохранения…' : 'Сохранить поступление'}
          </Button>
          <Link to={`/capture${item ? `?item_id=${item.id}` : ''}`} onClick={onClose}>
            Распознать по фото или голосу
          </Link>
        </fieldset>
      </form>
    </Modal>
  )
}
