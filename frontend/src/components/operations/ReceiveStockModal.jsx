import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { receiveStock } from '../../api/commands'
import { normalizeDecimal } from '../../utils/quantity'
import { useResource } from '../../hooks/useResource'
import { usePhotoUpload } from '../../hooks/usePhotoUpload'
import { Modal } from '../ui/Modal'
import { MediaCapture } from '../ui/MediaCapture'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { ReviewField } from '../review/ReviewField'
import { setCaptureDraft } from '../../utils/captureDraft'
import { OcrInput } from '../OcrInput'
import { useTasks } from '../../contexts/TaskContext'
import { randomId } from '../../utils/id'
import {
  fieldVisible,
  isItemProperty,
  optionalKeys,
  valueAt,
  withField,
} from '../../utils/itemFields'

export function ReceiveStockModal(props) {
  return props.isOpen ? <ReceiveForm {...props} /> : null
}
function ReceiveForm({
  onClose,
  onSuccess,
  item = null,
  locations = [],
  initialLocationId = '',
  initialName = '',
  initialPhotos = [],
  showCaptureLink = true,
}) {
  const [values, setValues] = useState({
    item_name: item?.name || initialName,
    category: item?.primary_category || 'other',
    tracking_mode: item?.tracking_mode || 'counted',
    unit_code: item?.attributes?.counting_unit === 'pair' ? 'pair' : item?.base_unit_id || 'pcs',
    quantity: '1',
    quantity_state: item?.tracking_mode === 'untracked' ? 'not_applicable' : 'exact',
    quantity_step: String(item?.quantity_step || '1'),
    location_id: initialLocationId,
    attributes: {},
    custom_attributes: {},
    privacy_policy: item?.privacy_policy || 'local_only',
  })
  const [fields, setFields] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [duplicate, setDuplicate] = useState(false)
  const [ocrBusy, setOcrBusy] = useState(false)
  const [modelPreference, setModelPreference] = useState('local')
  const [uncertain, setUncertain] = useState(false)
  const attempt = useRef(null)
  const submitting = useRef(false)
  const { addTask } = useTasks()
  const photo = usePhotoUpload(initialPhotos)
  const recognize = !item && !values.item_name.trim() && photo.photos.length > 0
  const { data: units } = useResource('/reference/units')
  const { data: categories } = useResource('/reference/categories')
  const { data: capabilities } = useResource('/capabilities')
  useEffect(() => {
    const controller = new AbortController()
    api(`/forms?operation=receive_stock&category=${values.category}`, { signal: controller.signal })
      .then((data) => setFields(data.fields))
      .catch((cause) => {
        if (cause.name !== 'AbortError') setError(cause.message)
      })
    return () => controller.abort()
  }, [values.category])
  const set = (key, value) => {
    setError('')
    if (key === 'item_name') setDuplicate(false)
    setValues((previous) => ({ ...previous, [key]: value }))
  }
  function attribute(field, value) {
    setValues((previous) => withField(previous, field.key, value))
  }
  async function submit(event) {
    event.preventDefault()
    if (submitting.current || photo.preparing || ocrBusy) return
    submitting.current = true
    setBusy(true)
    setError('')
    try {
      if (!item && !values.item_name.trim()) {
        if (!photo.photos.length)
          throw new Error('Укажите название вещи или прикрепите фото для распознавания.')
        const media_ids = await photo.upload(
          modelPreference === 'cloud' ? 'cloud_allowed' : 'local_only',
        )
        const body = {
          input_mode: 'photo',
          text: 'Добавить новую вещь по фотографии.',
          media_ids,
          context: { location_id: values.location_id || null },
          privacy: { force_local: modelPreference === 'local', model_preference: modelPreference },
        }
        const signature = JSON.stringify(body)
        if (attempt.current?.signature !== signature)
          attempt.current = {
            signature,
            key: randomId(),
            body: { ...body, client_request_id: randomId() },
          }
        const task = await api('/tasks', {
          method: 'POST',
          key: attempt.current.key,
          body: attempt.current.body,
        })
        addTask(task)
        onSuccess?.(task)
        onClose()
        return
      }
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
        lot_mode: 'create',
        location_id: values.location_id || null,
        unit_code: untracked ? null : values.unit_code,
        quantity,
        quantity_state: quantityState,
        quantity_step: normalizeDecimal(values.quantity_step),
        privacy_policy: values.category === 'document' ? 'local_only' : values.privacy_policy,
        media_ids: await photo.upload(),
      }
      body.expiry_precision = body.expiry_on ? 'day' : 'unknown'
      const result = await receiveStock(body, item ? { [`item:${item.id}`]: item.version } : {})
      onSuccess?.(result)
      onClose()
    } catch (cause) {
      if (cause.pending) {
        onClose()
        return
      }
      setUncertain(!!attempt.current && (!cause.status || cause.status >= 500))
      if (cause.status >= 400 && cause.status < 500 && cause.status !== 429) attempt.current = null
      setDuplicate(
        cause.review?.blocking_issues?.some((issue) => issue.code === 'DUPLICATE_CANDIDATE') ||
          false,
      )
      setError(cause.message)
    } finally {
      setBusy(false)
      submitting.current = false
    }
  }
  const reference = { locations, units: units?.items || [], items: item ? [item] : [] }
  const optional = fields.filter(
    (field) =>
      (isItemProperty(field.key) || optionalKeys.has(field.key)) && fieldVisible(field, values),
  )
  const context = new URLSearchParams()
  if (item) context.set('item_id', item.id)
  if (values.location_id) context.set('location_id', values.location_id)
  return (
    <Modal
      isOpen
      busy={busy}
      onClose={onClose}
      title={item ? `Пополнить: ${item.name}` : 'Добавить вещь'}
    >
      <form className="page-stack" onSubmit={submit}>
        <fieldset disabled={busy || uncertain} className="page-stack">
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {duplicate && (
            <label className="check">
              <input
                type="checkbox"
                checked={!!values.separate_item}
                onChange={(event) => set('separate_item', event.target.checked)}
              />
              Это другая вещь — создать отдельную карточку
            </label>
          )}
          <MediaCapture
            {...photo.capture}
            onMediaCaptured={(media) => {
              photo.capture.onMediaCaptured(media)
              setError('')
            }}
            disabled={busy || ocrBusy}
            maxPhotos={capabilities?.media_limits?.max_images || 3}
          />
          {!item && !fields.find((field) => field.key === 'ocr_text')?.hidden && (
            <OcrInput
              photo={photo}
              value={values.ocr_text}
              onChange={(text) => set('ocr_text', text)}
              disabled={busy}
              onBusyChange={setOcrBusy}
            />
          )}
          {!item && (
            <Input
              label="Название вещи"
              autoFocus
              value={values.item_name}
              onChange={(event) => set('item_name', event.target.value)}
              placeholder="Например, носки или зарядное устройство"
            />
          )}
          {recognize && (
            <>
              <p className="notice">
                Название не заполнено — запустим распознавание фото. Модель определит название,
                количество и свойства; выбранное место сохранится. Карточка появится сразу со
                статусом обработки.
              </p>
              <Select
                label="Модель распознавания"
                value={modelPreference}
                info="Локальная — доверенный сервер владельца. При выборе облака первичная проверка всё равно локальная. Чувствительные материалы и места с запретом облака остаются локально."
                onChange={(event) => setModelPreference(event.target.value)}
              >
                <option value="local">Локальная — доверенный сервер</option>
                <option
                  value="cloud"
                  disabled={!capabilities?.cloud_configured || !capabilities?.external_enabled}
                >
                  Облачная — после проверки приватности
                </option>
              </Select>
            </>
          )}
          {!recognize && values.tracking_mode !== 'untracked' && (
            <div className="quantity-fields">
              {values.quantity_state !== 'unknown' && (
                <Input
                  label="Количество"
                  required
                  inputMode="decimal"
                  value={values.quantity}
                  onChange={(event) => set('quantity', event.target.value)}
                />
              )}
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
            </div>
          )}
          <Select
            label="Место хранения"
            value={values.location_id}
            onChange={(event) => set('location_id', event.target.value)}
          >
            <option value="">Место не указано</option>
            {locations
              .filter((location) => location.kind !== 'system_unspecified')
              .map((location) => (
                <option key={location.id} value={location.id}>
                  {location.full_path || location.name}
                </option>
              ))}
          </Select>
          {!recognize && (
            <details>
              <summary>Категория, срок и другие сведения</summary>
              <div className="page-stack">
                {!item && (
                  <>
                    <Select
                      label="Категория"
                      value={values.category}
                      onChange={(event) =>
                        setValues((previous) => ({
                          ...previous,
                          category: event.target.value,
                          attributes: {},
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
                      label="Как учитывать"
                      value={values.tracking_mode}
                      onChange={(event) =>
                        setValues((previous) => ({
                          ...previous,
                          tracking_mode: event.target.value,
                          quantity_state:
                            event.target.value === 'untracked' ? 'not_applicable' : 'exact',
                          quantity_step: event.target.value === 'measured' ? '0.001' : '1',
                          unit_code: event.target.value === 'measured' ? 'g' : 'pcs',
                          quantity: '1',
                        }))
                      }
                    >
                      <option value="counted">По количеству</option>
                      <option value="measured">По весу или объёму</option>
                      <option value="individual">Уникальная вещь</option>
                      <option value="untracked">Только наличие</option>
                    </Select>
                  </>
                )}
                {values.tracking_mode !== 'untracked' && (
                  <Select
                    label="Точность количества"
                    value={values.quantity_state}
                    onChange={(event) => set('quantity_state', event.target.value)}
                  >
                    <option value="exact">Точное</option>
                    <option value="estimated">Примерное</option>
                    <option value="unknown">Неизвестно</option>
                  </Select>
                )}
                {(!fields.find((field) => field.key === 'expiry_on')?.hidden ||
                  values.expiry_on) && (
                  <Input
                    type="date"
                    label="Годен до (необязательно)"
                    value={values.expiry_on || ''}
                    onChange={(event) => set('expiry_on', event.target.value)}
                  />
                )}
                {!item &&
                  optional.map((field) => (
                    <ReviewField
                      key={field.key}
                      field={field}
                      references={reference}
                      value={valueAt(values, field.key)}
                      onChange={(value) =>
                        isItemProperty(field.key) ? attribute(field, value) : set(field.key, value)
                      }
                    />
                  ))}
              </div>
            </details>
          )}
          {showCaptureLink && !uncertain && (
            <Link
              to={`/capture?${context}`}
              onClick={() => {
                setCaptureDraft({ photos: photo.photos, text: item ? '' : values.item_name })
                onClose()
              }}
            >
              Заполнить по фото или голосу
            </Link>
          )}
        </fieldset>
        {uncertain && (
          <p className="notice">
            Сервер мог уже принять задачу. Повторите отправку: проверим тот же запрос без создания
            второй вещи.
          </p>
        )}
        <Button type="submit" disabled={busy || photo.preparing || ocrBusy}>
          {busy
            ? recognize
              ? 'Отправляем на распознавание…'
              : 'Сохраняем…'
            : uncertain
              ? 'Повторить отправку'
              : item
                ? 'Пополнить'
                : 'Добавить вещь'}
        </Button>
      </form>
    </Modal>
  )
}
