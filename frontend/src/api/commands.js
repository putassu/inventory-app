import { write } from './client'
import { submitConfirmation } from './confirmations'
export { normalizeDecimal } from '../utils/quantity'

export async function executeCommand(type, values, expectedVersions = {}, clientRequestId) {
  return executeBulkCommands([{ type, values }], expectedVersions, clientRequestId)
}

export async function executeBulkCommands(actions, expectedVersions = {}, clientRequestId) {
  if (!actions.length || actions.length > 50)
    throw new Error('Выберите от 1 до 50 действий за одно подтверждение.')
  const payload = {
    client_request_id: clientRequestId,
    actions: actions.map((a, i) => ({
      action_id: a.action_id || `a${i + 1}`,
      type: a.type,
      values: cleanValues(a.values),
    })),
    expected_versions: expectedVersions || {},
    explicit_confirmation: true,
  }

  return submitConfirmation('/commands/manual-confirm', payload)
}

export function cleanValues(values) {
  const cleaned = {}
  for (const [k, v] of Object.entries(values)) {
    if (v !== undefined && v !== '') {
      cleaned[k] = v
    }
  }
  return cleaned
}

// 1. Поступление / Создание вещи
export const receiveStock = (values, expectedVersions) =>
  executeCommand('receive_stock', values, expectedVersions)

// 2. Перемещение остатка
export const moveStock = (values, expectedVersions) =>
  executeCommand('move_stock', values, expectedVersions)

// 3. Расход остатка
export const consumeStock = (values, expectedVersions) =>
  executeCommand('consume_stock', values, expectedVersions)

// 4. Уточнить остаток (Инвентаризация)
export const setQuantity = (values, expectedVersions) =>
  executeCommand('set_quantity', values, expectedVersions)

// 5. Обновить карточку вещи
export const updateItem = (values, expectedVersions) =>
  executeCommand('update_item', values, expectedVersions)

// 6. Обновить партию
export const updateLot = (values, expectedVersions) =>
  executeCommand('update_lot', values, expectedVersions)

// 7. Разделить партию
export const splitLot = (values, expectedVersions) =>
  executeCommand('split_lot', values, expectedVersions)

// 8. Объединить партии
export const mergeLots = (lotIds, expectedVersions) =>
  executeCommand('merge_lots', { lot_ids: lotIds }, expectedVersions)

// 9. Создать место
export const createLocation = (values, expectedVersions) =>
  executeCommand('create_location', values, expectedVersions)

// 10. Переместить место (контейнер)
export const moveLocation = (values, expectedVersions) =>
  executeCommand('move_location', values, expectedVersions)

// 11. Обновить место
export const updateLocation = (values, expectedVersions) =>
  executeCommand('update_location', values, expectedVersions)

// 12. В архив вещь
export const archiveItem = (itemId, expectedVersions) =>
  executeCommand('archive_item', { item_id: itemId }, expectedVersions)

export const archiveItemsBulk = (items) =>
  executeBulkCommands(
    items.map((item) => ({ type: 'archive_item', values: { item_id: item.id } })),
    Object.fromEntries(items.map((item) => [`item:${item.id}`, item.version])),
  )

// 13. Восстановить вещь из архива
export const restoreItem = (itemId, expectedVersions) =>
  executeCommand('restore_item', { item_id: itemId }, expectedVersions)

// 14. В архив место
export const archiveLocation = (locationId, transferToId, expectedVersions) =>
  executeCommand(
    'archive_location',
    { location_id: locationId, transfer_to_id: transferToId || null },
    expectedVersions,
  )

// 15. Добавить алиас
export const addAlias = (itemId, alias, scope = 'workspace', expectedVersions) =>
  executeCommand('add_alias', { item_id: itemId, alias, scope }, expectedVersions)

// 16. Удалить алиас
export const removeAlias = (aliasId, expectedVersions) =>
  executeCommand('remove_alias', { alias_id: aliasId }, expectedVersions)

// 17. Подтвердить присутствие
export const confirmPresence = (lotId, locationId, expectedVersions) =>
  executeCommand('confirm_presence', { lot_id: lotId, location_id: locationId }, expectedVersions)

// 18. Отмена операции
export const reverseOperation = (operationId, expectedVersions) =>
  executeCommand('reverse_operation', { operation_id: operationId }, expectedVersions)

// Превью отмены операции
export const previewReverseOperation = (operationId) =>
  write(`/operations/${operationId}/reverse-preview`, {}, 'POST', crypto.randomUUID())
