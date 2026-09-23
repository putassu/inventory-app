import { useRef, useState } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { useToast } from '../../contexts/ToastContext'
import { updateLot, splitLot, mergeLots, normalizeDecimal } from '../../api/commands'

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
  const [expiryPrecision, setExpiryPrecision] = useState(lot?.expiry_precision || 'day')
  const [openedOn, setOpenedOn] = useState(lot?.opened_on || '')
  const [quantity, setQuantity] = useState('1')
  const [locationId, setLocationId] = useState(
    item?.balances?.find((row) => row.lot_id === lot?.id)?.location_id || '',
  )
  const [selectedLotIds, setSelectedLotIds] = useState(lot ? [lot.id] : [])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  const lots = item?.lots || []

  const titles = {
    update: 'Редактирование партии',
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
      if (operation === 'update') {
        result = await updateLot(
          {
            lot_id: lot.id,
            label: label.trim() || null,
            serial_number: serialNumber.trim() || null,
            manufacturer_batch: batch.trim() || null,
            expiry_on: expiryOn || null,
            expiry_precision: expiryOn ? expiryPrecision : undefined,
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
            expiry_on: expiryOn || null,
            expiry_precision: expiryOn ? expiryPrecision : 'unknown',
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
      title={titles[operation] || 'Операция с партией'}
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
                    label={`Количество для отделения (${item?.base_unit_id || 'шт.'})`}
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
                    {locations.map((loc) => (
                      <option key={loc.id} value={loc.id}>
                        {loc.full_path || loc.name}
                      </option>
                    ))}
                  </Select>
                </>
              )}

              <Input
                label={operation === 'split' ? 'Метка новой партии' : 'Метка партии'}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Обозначение или примечание"
              />

              <div
                style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-3)' }}
              >
                <Input
                  label="Серийный номер"
                  value={serialNumber}
                  onChange={(e) => setSerialNumber(e.target.value)}
                />
                <Input
                  label="Номер партии (Батч)"
                  value={batch}
                  onChange={(e) => setBatch(e.target.value)}
                />
              </div>

              <div
                style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 'var(--space-3)' }}
              >
                <Input
                  label="Срок годности"
                  type="date"
                  value={expiryOn}
                  onChange={(e) => setExpiryOn(e.target.value)}
                />
                <Select
                  label="Точность"
                  value={expiryPrecision}
                  onChange={(e) => setExpiryPrecision(e.target.value)}
                  disabled={!expiryOn}
                >
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
