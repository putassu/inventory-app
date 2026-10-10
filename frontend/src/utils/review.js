import { normalizeDecimal } from './quantity'
import { fieldVisible, withField } from './itemFields'

export function reviewValue(field, value) {
  if (field?.key?.startsWith('custom_attributes.') && field.value_type === 'decimal')
    return value === '' ? null : String(value).replace(',', '.')
  if (!['number_stepper', 'decimal_input'].includes(field?.control)) return value
  const normalized = normalizeDecimal(value)
  if (normalized === null || field.value_type !== 'integer') return normalized
  const integer = Number(normalized)
  if (!Number.isSafeInteger(integer))
    throw new Error(`«${field.label || field.key}»: введите целое число.`)
  return integer
}

const order = [
  'item_mode',
  'item_id',
  'item_name',
  'name',
  'category',
  'tracking_mode',
  'quantity_state',
  'quantity',
  'unit_code',
  'location_id',
  'to_location_id',
  'whole_presence',
  'lot_mode',
  'lot_id',
  'lot_ids',
  'expiry_precision',
  'expiry_on',
  'reason',
]

export function fieldValue(action, field, changes) {
  const edit = changes[`${field.action_id}:${field.key}`]
  if (edit) return edit.value
  const value = field.key.split('.').reduce((current, key) => current?.[key], action.values)
  return value === undefined ? field.value : value
}

export function reviewFields(action, fields, changes) {
  let values = { ...action.values }
  for (const edit of Object.values(changes))
    if (edit.action_id === action.action_id) values = withField(values, edit.key, edit.value)
  return fields
    .filter((field) => {
      if (field.action_id !== action.action_id) return false
      if (!field.required && !fieldVisible(field, values)) return false
      if (!['receive_stock', 'verify_item'].includes(action.type)) return true
      const key = field.key
      if (key === 'lot_mode' || (key === 'lot_id' && values.lot_mode !== 'existing')) return false
      if (
        key === 'expiry_on' &&
        (!values.expiry_precision || values.expiry_precision === 'unknown')
      )
        return false
      if (key === 'item_id' && values.item_mode === 'create') return false
      if (
        values.item_mode === 'existing' &&
        ([
          'item_name',
          'category',
          'tracking_mode',
          'brand',
          'model',
          'barcode',
          'user_description',
          'generated_description',
          'tags',
          'quantity_step',
          'separate_item',
        ].includes(key) ||
          key.startsWith('attributes.') ||
          key.startsWith('custom_attributes.'))
      )
        return false
      if (key === 'lot_id' && values.lot_mode !== 'existing') return false
      if (
        values.tracking_mode === 'untracked' &&
        ['quantity', 'quantity_state', 'unit_code', 'quantity_step'].includes(key)
      )
        return false
      if (key === 'quantity' && ['unknown', 'not_applicable'].includes(values.quantity_state))
        return false
      return true
    })
    .sort((a, b) => {
      const rank = (field) => (order.includes(field.key) ? order.indexOf(field.key) : 100)
      return rank(a) - rank(b)
    })
}

export const primaryField = (field) =>
  field.required ||
  [
    'item_id',
    'item_name',
    'name',
    'quantity',
    'unit_code',
    'location_id',
    'to_location_id',
    'lot_id',
    'lot_ids',
    'whole_presence',
  ].includes(field.key)
// Старые подсказки распознавания не должны выглядеть как новые ошибки после выбора пользователя.
export function activeWarnings(review, changes) {
  return (review.warnings || []).filter((warning) => {
    if (typeof warning !== 'string') return true
    if (warning.startsWith('Место из ввода не выбрано:'))
      return !review.actions.every((action) => changes[`${action.action_id}:location_id`])
    if (
      warning.startsWith('Найдены похожие вещи:') ||
      warning.includes('Выберите действие вручную')
    )
      return !review.actions.every((action) => changes[`${action.action_id}:operation`])
    return true
  })
}
