import { useRef, useState } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { useToast } from '../../contexts/ToastContext'
import { updateLot, splitLot, mergeLots, normalizeDecimal } from '../../api/commands'
import { unitLabel, scaled } from '../../utils/quantity'

export function LotOperationsModal(props) {
  return props.isOpen ? <Form {...props} /> : null
}
function Form({
  isOpen,
  onClose,
  onSuccess,
  item,
  lot = null,
  locations = [],
  operation = 'update', // 'update' | 'split' | 'merge'
}) {
  const { addToast } = useToast()
  const submitting = useRef(false)

  const [label, setLabel] = useState(lot?.label || '')
  const [serialNumber, setSerialNumber] = useState(lot?.serial_number || '')
  const [batch, setBatch] = useState(lot?.manufacturer_batch || '')
  const [expiryOn, setExpiryOn] = useState(lot?.expiry_on || '')
  const [expiryPrecision, setExpiryPrecision] = useState(lot?.expiry_precision || 'unknown')
  const [openedOn, setOpenedOn] = useState(lot?.opened_on || '')
  const [quantity, setQuantity] = useState('1')
  const [locationId, setLocationId] = useState(
    item?.balances?.find(
      (row) => row.lot_id === lot?.id && row.quantity != null && scaled(row.quantity) > 0n,
    )?.location_id || '',
  )
  const [selectedLotIds, setSelectedLotIds] = useState(lot ? [lot.id] : [])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  const lots = (item?.lots || []).filter((row) => !row.archived_at)

  const titles = {
    update: 'Срок и сведения о вещи',
    split: 'Разделение партии',
    merge: 'Объединение партий',
  }

  const handleToggleLotSelect = (id) => {
    setSelectedLotIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting.current) return
    submitting.current = true
    setIsLoading(true)
    setError(null)

    try {
      const expectedVersions = {}
      if (item?.version) expectedVersions[`item:${item.id}`] = item.version
      if (lot?.version) expectedVersions[`lot:${lot.id}`] = lot.version
      for (const selected of lots.filter((row) => selectedLotIds.includes(row.id)))
        expectedVersions[`lot:${selected.id}`] = selected.version
      for (const balance of item?.balances || [])
        if (balance.lot_id === lot?.id || selectedLotIds.includes(balance.lot_id))
          expectedVersions[`balance:${balance.id}`] = balance.version

      let result
      const expiry =
        expiryPrecision === 'unknown' || !expiryOn
          ? null
          : expiryPrecision === 'month'
            ? `${expiryOn.slice(0, 7)}-01`
            : expiryOn
      if (operation === 'update') {
        result = await updateLot(
          {
            lot_id: lot.id,
            label: label.trim() || null,
            serial_number: serialNumber.trim() || null,
            manufacturer_batch: batch.trim() || null,
            expiry_on: expiry,
            expiry_precision: expiry ? expiryPrecision : 'unknown',
            opened_on: openedOn || null,
          },
          expectedVersions,
        )
        addToast('Партия успешно обновлена', 'success')
      } else if (operation === 'split') {
        const decQty = normalizeDecimal(quantity)
        result = await splitLot(
          {
            lot_id: lot.id,
            location_id: locationId || null,
            quantity: decQty,
            label: label.trim() || null,
            serial_number: serialNumber.trim() || null,
            manufacturer_batch: batch.trim() || null,
            expiry_on: expiry,
            expiry_precision: expiry ? expiryPrecision : 'unknown',
            opened_on: openedOn || null,
          },
          expectedVersions,
        )
        addToast('Партия успешно разделена', 'success')
      } else if (operation === 'merge') {
        if (selectedLotIds.length < 2) {
          throw new Error('Выберите минимум 2 партии для объединения')
        }
        result = await mergeLots(selectedLotIds, expectedVersions)
        addToast('Партии успешно объединены', 'success')
      }

      if (onSuccess) onSuccess(result)
      onClose()
    } catch (err) {
      if (err.pending) {
        onClose()
        return
      }
      setError(err.message || 'Ошибка выполнения действия')
    } finally {
      submitting.current = false
      setIsLoading(false)
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      busy={isLoading}
      onClose={onClose}
      title={titles[operation] || 'Сведения о вещи'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isLoading}>
            Отмена
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isLoading}>
            {isLoading ? 'Сохранение...' : operation === 'merge' ? 'Объединить' : 'Сохранить'}
          </Button>
        </>
      }
    >
      <form
        onSubmit={handleSubmit}
        style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}
      >
        <fieldset disabled={isLoading} className="page-stack">
          {error && (
            <div
              role="alert"
              style={{
                padding: 'var(--space-3)',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid var(--danger)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--danger)',
                fontSize: '14px',
              }}
            >
              {error}
            </div>
          )}

          {operation === 'merge' ? (
            <div>
              <div style={{ fontSize: '14px', marginBottom: 'var(--space-2)' }}>
                Выберите от 2 до 20 партий для объединения:
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                {lots.map((l) => (
                  <label
                    key={l.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 'var(--space-2)',
                      padding: 'var(--space-2)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--radius-sm)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={selectedLotIds.includes(l.id)}
                      onChange={() => handleToggleLotSelect(l.id)}
                    />
                    <div>
                      <div style={{ fontWeight: 500, fontSize: '14px' }}>
                        {l.label || `Партия ${l.id.slice(0, 8)}`}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                        {l.expiry_on ? `Срок: ${l.expiry_on}` : 'Без срока'}
                        {l.manufacturer_batch ? ` • Батч: ${l.manufacturer_batch}` : ''}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          ) : (
            <>
              {operation === 'split' && (
                <>
                  <Input
                    label={`Количество для отделения (${unitLabel(item?.base_unit_id) || 'шт.'})`}
                    type="text"
                    inputMode="decimal"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    required
                  />
                  <Select
                    label="Местоположение выделяемого остатка"
                    value={locationId}
                    onChange={(e) => setLocationId(e.target.value)}
                  >
                    {locations
                      .filter((loc) =>
                        item?.balances?.some(
                          (balance) =>
                            balance.location_id === loc.id &&
                            balance.lot_id === lot?.id &&
                            balance.quantity != null &&
                            scaled(balance.quantity) > 0n,
                        ),
                      )
                      .map((loc) => (
                        <option key={loc.id} value={loc.id}>
                          {loc.full_path || loc.name}
                        </option>
                      ))}
                  </Select>
                </>
              )}

              <Input
                label="Примечание"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Обозначение или примечание"
              />

              <div className="form-grid">
                <Input
                  label="Серийный номер"
                  value={serialNumber}
                  onChange={(e) => setSerialNumber(e.target.value)}
                />
                <Input
                  label="Код производителя (необязательно)"
                  value={batch}
                  onChange={(e) => setBatch(e.target.value)}
                />
              </div>

              <div className="form-grid">
                <Input
                  label="Срок годности"
                  type={expiryPrecision === 'month' ? 'month' : 'date'}
                  value={expiryPrecision === 'month' ? expiryOn.slice(0, 7) : expiryOn}
                  onChange={(e) => {
                    setExpiryOn(e.target.value)
                    if (expiryPrecision === 'unknown') setExpiryPrecision('day')
                  }}
                />
                <Select
                  label="Точность"
                  value={expiryPrecision}
                  onChange={(e) => {
                    setExpiryPrecision(e.target.value)
                    if (e.target.value === 'unknown') setExpiryOn('')
                  }}
                >
                  <option value="unknown">Неизвестно</option>
                  <option value="day">День</option>
                  <option value="month">Месяц</option>
                </Select>
              </div>

              <Input
                label="Дата вскрытия упаковки"
                type="date"
                value={openedOn}
                onChange={(e) => setOpenedOn(e.target.value)}
              />
            </>
          )}
        </fieldset>
      </form>
    </Modal>
  )
}
