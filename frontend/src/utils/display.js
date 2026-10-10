import { label } from './labels'
import { displayDecimal, unitLabel } from './quantity'

export function describeValue(value, key = '', locations = []) {
  if (value == null || value === '') return 'Не указано'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  if (Array.isArray(value))
    return value.map((part) => describeValue(part, key, locations)).join(', ') || 'Нет'
  if (typeof value === 'object')
    return (
      Object.entries(value)
        .map(([name, part]) => `${label(name)}: ${describeValue(part, name, locations)}`)
        .join('; ') || 'Нет'
    )
  if (['location_id', 'parent_id'].includes(key))
    return locations.find((row) => row.id === value)?.full_path || 'Место недоступно'
  if (key === 'quantity') return displayDecimal(value)
  if (['unit_code', 'base_unit_id', 'counting_unit'].includes(key)) return unitLabel(value)
  return [
    'quantity_state',
    'primary_category',
    'tracking_mode',
    'privacy_policy',
    'lifecycle',
    'expiry_precision',
    'after_opening_unit',
  ].includes(key)
    ? label(value)
    : String(value)
}
