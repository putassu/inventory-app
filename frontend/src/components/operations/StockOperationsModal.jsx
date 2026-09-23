import { useRef, useState } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { useToast } from '../../contexts/ToastContext'
import {
  consumeStock,
  moveStock,
  setQuantity,
  confirmPresence,
  normalizeDecimal,
} from '../../api/commands'

export function StockOperationsModal(props) {
  return props.isOpen ? <Form {...props} /> : null
}
function Form({
  isOpen,
  onClose,
  onSuccess,
  item,
  initialLot,
  initialBalance,
  locations = [],
  operation = 'consume', // 'consume' | 'move' | 'set_quantity' | 'confirm_presence'
}) {
  const { addToast } = useToast()
  const submitting = useRef(false)
  const [selectedLotId, setSelectedLotId] = useState(initialLot?.id || item?.lots?.[0]?.id || '')
  const [selectedLocationId, setSelectedLocationId] = useState(
    initialBalance?.location_id ||
      item?.balances?.find((row) => row.lot_id === (initialLot?.id || item?.lots?.[0]?.id))
        ?.location_id ||
      '',
  )
  const [toLocationId, setToLocationId] = useState(
    locations.find((row) => row.id !== initialBalance?.location_id)?.id || '',
  )
  const [quantity, setQuantityVal] = useState(initialBalance?.quantity ?? '1')
  const [quantityState, setQuantityState] = useState(initialBalance?.quantity_state || 'exact')
  const [wholePresence, setWholePresence] = useState(false)
  const [reason, setReason] = useState(operation === 'consume' ? 'Расход' : 'Корректировка')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  const lots = item?.lots || []
  const balances = item?.balances || []

  // Find relevant balance for the selected lot and location
  const currentBalance = balances.find(
    (b) => b.lot_id === selectedLotId && b.location_id === selectedLocationId,
  )

  const titles = {
    consume: 'Списание / Расход',
    move: 'Перемещение',
    set_quantity: 'Уточнение остатка (Инвентаризация)',
    confirm_presence: 'Подтверждение присутствия',
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
      const lot = lots.find((l) => l.id === selectedLotId)
      if (lot?.version) expectedVersions[`lot:${lot.id}`] = lot.version
      if (currentBalance?.version)
        expectedVersions[`balance:${currentBalance.id}`] = currentBalance.version

      let result
      if (operation === 'consume') {
        const decQty = normalizeDecimal(quantity)
        result = await consumeStock(
          {
            lot_id: selectedLotId || null,
            location_id: selectedLocationId || null,
            quantity: decQty,
            unit_code: item?.base_unit_id || 'pcs',
            reason: reason || 'Расход',
          },
          expectedVersions,
        )
        addToast('Остаток успешно списан', 'success')
      } else if (operation === 'move') {
        if (!toLocationId) throw new Error('Выберите место назначения')
        const decQty = wholePresence ? null : normalizeDecimal(quantity)
        result = await moveStock(
          {
            lot_id: selectedLotId || null,
            location_id: selectedLocationId || null,
            to_location_id: toLocationId,
            quantity: decQty,
            unit_code: item?.base_unit_id || 'pcs',
            whole_presence: wholePresence,
          },
          expectedVersions,
        )
        addToast('Остаток успешно перемещен', 'success')
      } else if (operation === 'set_quantity') {
        const decQty = ['unknown', 'not_applicable'].includes(quantityState)
          ? null
          : normalizeDecimal(quantity)
        result = await setQuantity(
          {
            lot_id: selectedLotId || null,
            location_id: selectedLocationId || null,
            quantity: decQty,
            quantity_state: quantityState,
            reason: reason || 'Корректировка',
          },
          expectedVersions,
        )
        addToast('Остаток успешно обновлен', 'success')
      } else if (operation === 'confirm_presence') {
        result = await confirmPresence(
          selectedLotId || null,
          selectedLocationId || null,
          expectedVersions,
        )
        addToast('Присутствие подтверждено', 'success')
      }

      if (onSuccess) onSuccess(result)
      onClose()
    } catch (err) {
      let errMsg = err.message || 'Ошибка выполнения операции'
      if (err.fields) {
        errMsg += ` (${Object.entries(err.fields)
          .map(([k, v]) => `${k}: ${v}`)
          .join('; ')})`
      } else if (err.details && Array.isArray(err.details)) {
        errMsg += ` (${err.details.map((d) => `${d.loc?.join('.')}: ${d.msg}`).join('; ')})`
      }
      setError(errMsg)
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
      title={titles[operation] || 'Операция с остатком'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isLoading}>
            Отмена
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isLoading}>
            {isLoading ? 'Сохранение...' : 'Подтвердить'}
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

          <div style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
            Вещь: <strong>{item?.name}</strong>
          </div>

          {lots.length > 1 && (
            <Select
              label="Партия"
              value={selectedLotId}
              onChange={(e) => {
                setSelectedLotId(e.target.value)
                setSelectedLocationId(
                  balances.find((balance) => balance.lot_id === e.target.value)?.location_id || '',
                )
              }}
            >
              {lots.map((lot) => (
                <option key={lot.id} value={lot.id}>
                  {lot.label ||
                    `Партия от ${lot.acquired_at || lot.created_at?.slice(0, 10) || lot.id.slice(0, 8)}`}
                </option>
              ))}
            </Select>
          )}

          <Select
            label="Исходное место хранения"
            value={selectedLocationId}
            onChange={(e) => setSelectedLocationId(e.target.value)}
          >
            {locations
              .filter((loc) =>
                balances.some(
                  (balance) => balance.lot_id === selectedLotId && balance.location_id === loc.id,
                ),
              )
              .map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.full_path || loc.name}
                </option>
              ))}
          </Select>

          {currentBalance && (
            <div
              style={{
                fontSize: '13px',
                padding: 'var(--space-2) var(--space-3)',
                backgroundColor: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                justifyContent: 'space-between',
              }}
            >
              <span>Текущий остаток в месте:</span>
              <strong>
                {currentBalance.quantity_state === 'unknown'
                  ? 'Неизвестно'
                  : `${currentBalance.quantity} ${currentBalance.unit_code || item?.base_unit_id || 'шт.'}`}
              </strong>
            </div>
          )}

          {operation === 'move' && (
            <>
              <Select
                label="Куда переместить"
                value={toLocationId}
                onChange={(e) => setToLocationId(e.target.value)}
                required
              >
                <option value="">-- Выберите место назначения --</option>
                {locations
                  .filter((l) => l.id !== selectedLocationId)
                  .map((loc) => (
                    <option key={loc.id} value={loc.id}>
                      {loc.full_path || loc.name}
                    </option>
                  ))}
              </Select>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--space-2)',
                  fontSize: '14px',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={wholePresence}
                  onChange={(e) => setWholePresence(e.target.checked)}
                />
                Переместить весь остаток целиком (whole presence)
              </label>
            </>
          )}

          {operation === 'set_quantity' && (
            <Select
              label="Состояние количества"
              value={quantityState}
              onChange={(e) => setQuantityState(e.target.value)}
            >
              <option value="exact">Точное число (exact)</option>
              <option value="estimated">Примерное количество (estimated)</option>
              <option value="unknown">Неизвестно (unknown)</option>
              <option value="not_applicable">Учёт присутствия (not_applicable)</option>
            </Select>
          )}

          {!(
            operation === 'confirm_presence' ||
            (operation === 'move' && wholePresence) ||
            (operation === 'set_quantity' && ['unknown', 'not_applicable'].includes(quantityState))
          ) && (
            <Input
              label={`Количество (${item?.base_unit_id || 'шт.'})`}
              type="text"
              inputMode="decimal"
              value={quantity}
              onChange={(e) => setQuantityVal(e.target.value)}
              placeholder="Например, 1 или 1.5"
              required
            />
          )}

          {(operation === 'consume' || operation === 'set_quantity') && (
            <Input
              label="Причина"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Укажите причину операции"
            />
          )}
        </fieldset>
      </form>
    </Modal>
  )
}
