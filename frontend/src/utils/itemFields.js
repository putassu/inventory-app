export const valueAt = (values, key) =>
  key.split('.').reduce((value, part) => value?.[part], values)
export const hasValue = (value) =>
  value !== null &&
  value !== undefined &&
  value !== '' &&
  (!Array.isArray(value) || value.length > 0)
export const fieldVisible = (field, values) => !field.hidden || hasValue(valueAt(values, field.key))
export const optionalKeys = new Set([
  'brand',
  'model',
  'barcode',
  'user_description',
  'tags',
  'serial_number',
  'opened_on',
  'after_opening_amount',
  'after_opening_unit',
  'package_size',
])
export const isItemProperty = (key) =>
  key.startsWith('attributes.') || key.startsWith('custom_attributes.')

export function withField(values, key, value) {
  const next = structuredClone(values)
  const parts = key.split('.')
  let target = next
  for (const part of parts.slice(0, -1)) target = target[part] ||= {}
  const last = parts.at(-1)
  if (parts.length > 1 && value === null) delete target[last]
  else target[last] = value
  return next
}
