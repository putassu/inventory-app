import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { executeBulkCommands } from '../../api/commands'
import { useResource } from '../../hooks/useResource'
import { usePhotoUpload } from '../../hooks/usePhotoUpload'
import { countingQuantity, editableStocks, editItemCommands } from '../../utils/editItem'
import { fieldVisible, isItemProperty, valueAt, withField } from '../../utils/itemFields'
import { unitLabel } from '../../utils/quantity'
import { label } from '../../utils/labels'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { MediaCapture } from '../ui/MediaCapture'
import { Thumbnail } from '../ui/Thumbnail'
import { ReviewField } from '../review/ReviewField'
import { OcrInput } from '../OcrInput'

const itemKeys = [
  'name',
  'primary_category',
  'brand',
  'model',
  'barcode',
  'tags',
  'user_description',
  'ocr_text',
  'attributes',
  'custom_attributes',
]
const extraKeys = new Set(['brand', 'model', 'barcode', 'tags', 'user_description'])

export function EditItemModal({ item, locations, onClose, onSuccess }) {
  const [values, setValues] = useState(() =>
    Object.fromEntries(itemKeys.map((key) => [key, item[key]])),
  )
  const [stocks, setStocks] = useState(() => editableStocks(item))
  const [lots, setLots] = useState(() =>
    item.lots.filter((lot) => !lot.archived_at).map((lot) => ({ ...lot })),
  )
  const [busy, setBusy] = useState(false),
    [ocrBusy, setOcrBusy] = useState(false),
    [error, setError] = useState('')
  const submitting = useRef(false)
  const photo = usePhotoUpload()
  const schema = useResource(`/forms?operation=receive_stock&category=${values.primary_category}`)
  const categories = useResource('/reference/categories')
  const capabilities = useResource('/capabilities')
  const set = (key, value) => {
    setError('')
    setValues((previous) => withField(previous, key, value))
  }
  const setStock = (id, patch) => {
    setError('')
    setStocks((previous) => previous.map((row) => (row.id === id ? { ...row, ...patch } : row)))
  }
  const setLot = (id, patch) => {
    setError('')
    setLots((previous) => previous.map((row) => (row.id === id ? { ...row, ...patch } : row)))
  }
  const shown = (key, data) =>
    fieldVisible(schema.data?.fields.find((field) => field.key === key) || { key }, data)
  const optional = (schema.data?.fields || []).filter(
    (field) =>
      (extraKeys.has(field.key) || isItemProperty(field.key)) && fieldVisible(field, values),
  )
  async function submit(event) {
    event.preventDefault()
    if (submitting.current || photo.preparing || ocrBusy) return
    submitting.current = true
    setBusy(true)
    setError('')
    try {
      if (!values.name.trim()) throw new Error('Укажите название вещи.')
      const next = {
        ...values,
        name: values.name.trim(),
        user_description: values.user_description?.trim() || null,
      }
      const command = editItemCommands(item, next, stocks, lots, await photo.upload())
      if (!command.actions.length) {
        onClose()
        return
      }
      const result = await executeBulkCommands(command.actions, command.versions)
      onSuccess?.(result)
      onClose()
    } catch (cause) {
      if (cause.pending) onClose()
      else setError(cause.message)
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }
  return (
    <Modal isOpen busy={busy} title="Редактировать вещь" onClose={onClose}>
      <form className="page-stack" onSubmit={submit}>
        <fieldset className="page-stack" disabled={busy}>
          {(error || schema.error) && (
            <p className="error" role="alert">
              {error || schema.error.message}
            </p>
          )}
          <Input
            label="Название вещи"
            autoFocus
            required
            maxLength={255}
            value={values.name}
            onChange={(event) => set('name', event.target.value)}
          />
          <div className="photo-strip">
            {item.photos?.map((row) => (
              <Thumbnail key={row.media_id} mediaId={row.thumbnail?.media_id} alt={item.name} />
            ))}
          </div>
          <MediaCapture
            {...photo.capture}
            disabled={busy || ocrBusy}
            maxPhotos={capabilities.data?.media_limits?.max_images || 3}
          />
          <p className="hint">Новые фотографии добавятся к существующим.</p>
          <Select
            label="Категория"
            value={values.primary_category}
            onChange={(event) => {
              const category = categories.data?.items.find((row) => row.code === event.target.value)
              setValues((previous) => ({
                ...previous,
                primary_category: event.target.value,
                attributes: Object.fromEntries(
                  Object.entries(previous.attributes || {}).filter(([key]) =>
                    category?.attributes.includes(key),
                  ),
                ),
              }))
            }}
          >
            {categories.data?.items.map((row) => (
              <option key={row.code} value={row.code}>
                {row.name}
              </option>
            ))}
          </Select>
          <p className="hint">
            {label(item.tracking_mode)} · {unitLabel(item.base_unit_id)}
          </p>
          {lots.map((lot, index) => (
            <fieldset className="card page-stack" key={lot.id}>
              <legend>{lots.length > 1 ? `Где и сколько · ${index + 1}` : 'Где и сколько'}</legend>
              {stocks
                .filter((row) => row.lot_id === lot.id)
                .map((row) => (
                  <div className="page-stack" key={row.id}>
                    {item.tracking_mode !== 'untracked' && (
                      <>
                        <div className="quantity-fields">
                          {row.quantity_state !== 'unknown' && (
                            <Input
                              label="Количество"
                              inputMode="decimal"
                              required
                              value={row.quantity}
                              onChange={(event) =>
                                setStock(row.id, { quantity: event.target.value })
                              }
                            />
                          )}
                          {item.base_unit_id === 'pcs' ? (
                            <Select
                              label="Единица"
                              value={row.unit}
                              onChange={(event) => {
                                const unit = event.target.value
                                try {
                                  setStock(row.id, {
                                    unit,
                                    quantity: countingQuantity(row.quantity, unit),
                                  })
                                } catch (cause) {
                                  setError(cause.message)
                                }
                              }}
                            >
                              <option value="pcs">шт.</option>
                              <option value="pair">пара</option>
                            </Select>
                          ) : (
                            <p>{unitLabel(item.base_unit_id)}</p>
                          )}
                        </div>
                        <Select
                          label="Точность количества"
                          value={row.quantity_state}
                          onChange={(event) =>
                            setStock(row.id, { quantity_state: event.target.value })
                          }
                        >
                          <option value="exact">Точное</option>
                          <option value="estimated">Примерное</option>
                          <option value="unknown">Неизвестно</option>
                        </Select>
                      </>
                    )}
                    <Select
                      label="Место хранения"
                      value={row.location_id}
                      onChange={(event) => setStock(row.id, { location_id: event.target.value })}
                    >
                      {locations.map((place) => (
                        <option key={place.id} value={place.id}>
                          {place.full_path || place.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                ))}
              {shown('expiry_on', lot) && (
                <Input
                  label="Годен до"
                  type="date"
                  value={lot.expiry_on || ''}
                  onChange={(event) =>
                    setLot(lot.id, {
                      expiry_on: event.target.value || null,
                      expiry_precision: event.target.value ? 'day' : 'unknown',
                      expiry_raw_text: null,
                    })
                  }
                />
              )}
              <details>
                <summary>Другие сведения о сроке и экземпляре</summary>
                <div className="page-stack">
                  {(schema.data?.fields || [])
                    .filter(
                      (field) =>
                        [
                          'serial_number',
                          'opened_on',
                          'after_opening_amount',
                          'after_opening_unit',
                        ].includes(field.key) && fieldVisible(field, lot),
                    )
                    .map((field) => (
                      <ReviewField
                        key={field.key}
                        field={field}
                        value={lot[field.key]}
                        onChange={(value) =>
                          setLot(lot.id, { [field.key]: value === '' ? null : value })
                        }
                      />
                    ))}
                </div>
              </details>
            </fieldset>
          ))}
          <details>
            <summary>Дополнительные свойства</summary>
            <div className="page-stack">
              {optional.map((field) => (
                <ReviewField
                  key={field.key}
                  field={field}
                  value={valueAt(values, field.key)}
                  onChange={(value) => set(field.key, value)}
                />
              ))}
              {shown('ocr_text', values) && (
                <OcrInput
                  photo={photo}
                  value={values.ocr_text}
                  onChange={(value) => set('ocr_text', value)}
                  disabled={busy}
                  onBusyChange={setOcrBusy}
                />
              )}
              <Link to="/settings" onClick={onClose}>
                Настроить список полей
              </Link>
            </div>
          </details>
          <div className="actions">
            <Button type="submit" disabled={busy || photo.preparing || ocrBusy || !schema.data}>
              {busy ? 'Сохраняем…' : 'Сохранить изменения'}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              Отмена
            </Button>
          </div>
        </fieldset>
      </form>
    </Modal>
  )
}
