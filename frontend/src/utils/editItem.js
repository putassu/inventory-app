import { decimal, normalizeDecimal, scaled } from './quantity'

export function countingQuantity(value, unit) {
  if (value === '') return ''
  const amount = scaled(value)
  if (unit === 'pair' && amount % 2n)
    throw new Error('Это количество нельзя выразить в парах без округления. Оставьте штуки.')
  return decimal(unit === 'pair' ? amount / 2n : amount * 2n)
}

export function editableStocks(item) {
  const lots = new Set(item.lots.filter((lot) => !lot.archived_at).map((lot) => lot.id))
  return visibleStocks(item)
    .filter((row) => lots.has(row.lot_id))
    .map((row) => {
      const pairs =
        item.base_unit_id === 'pcs' &&
        item.attributes?.counting_unit === 'pair' &&
        row.quantity != null &&
        scaled(row.quantity) % 2000000n === 0n
      return {
        ...row,
        unit: pairs ? 'pair' : item.base_unit_id,
        quantity:
          row.quantity == null
            ? ''
            : pairs
              ? decimal(scaled(row.quantity) / 2n)
              : String(row.quantity),
      }
    })
}

export function visibleStocks(item) {
  const present = (row) => row.quantity == null || scaled(row.quantity) !== 0n
  return item.balances.filter(
    (row) =>
      present(row) || !item.balances.some((other) => other.lot_id === row.lot_id && present(other)),
  )
}

export function editItemCommands(item, values, stocks, lots, mediaIds = []) {
  const actions = [],
    moves = [],
    versions = { [`item:${item.id}`]: item.version }
  const update = { item_id: item.id }
  for (const [key, value] of Object.entries(values))
    if (JSON.stringify(value) !== JSON.stringify(item[key])) update[key] = value
  if (mediaIds.length) update.media_ids = mediaIds
  if (Object.keys(update).length > 1) actions.push({ type: 'update_item', values: update })
  for (const lot of lots) {
    const original = item.lots.find((row) => row.id === lot.id)
    const patch = { lot_id: lot.id }
    for (const key of [
      'expiry_on',
      'expiry_precision',
      'expiry_raw_text',
      'serial_number',
      'opened_on',
      'after_opening_amount',
      'after_opening_unit',
    ])
      if (lot[key] !== original[key]) patch[key] = lot[key]
    if (Object.keys(patch).length > 1) actions.push({ type: 'update_lot', values: patch })
    versions[`lot:${lot.id}`] = original.version
  }
  for (const row of stocks) {
    const original = item.balances.find((balance) => balance.id === row.id)
    versions[`balance:${row.id}`] = original.version
    const quantity = ['unknown', 'not_applicable'].includes(row.quantity_state)
      ? null
      : normalizeDecimal(row.quantity)
    if (quantity === null && !['unknown', 'not_applicable'].includes(row.quantity_state))
      throw new Error('Укажите количество или выберите «Неизвестно».')
    const baseQuantity =
      quantity === null ? null : row.unit === 'pair' ? decimal(scaled(quantity) * 2n) : quantity
    if (
      baseQuantity !== null &&
      item.tracking_mode === 'individual' &&
      scaled(baseQuantity) > 1000000n
    )
      throw new Error('Уникальный экземпляр не может иметь количество больше одного.')
    if (
      (baseQuantity === null) !== (original.quantity === null) ||
      (baseQuantity !== null && scaled(baseQuantity) !== scaled(original.quantity)) ||
      row.quantity_state !== original.quantity_state
    )
      actions.push({
        type: 'set_quantity',
        values: {
          lot_id: row.lot_id,
          location_id: original.location_id,
          quantity: baseQuantity,
          quantity_state: row.quantity_state,
          reason: 'Редактирование карточки',
        },
      })
    if (row.location_id !== original.location_id)
      moves.push({
        type: 'move_stock',
        values: {
          lot_id: row.lot_id,
          location_id: original.location_id,
          to_location_id: row.location_id,
          quantity: baseQuantity,
          unit_code: item.base_unit_id,
          whole_presence: baseQuantity === null,
        },
      })
  }
  return { actions: [...actions, ...moves], versions }
}
