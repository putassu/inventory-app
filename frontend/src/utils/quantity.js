const SCALE = 1000000n
export function normalizeDecimal(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null
  const text = String(value).trim().replace(',', '.')
  if (!/^\d{1,14}(?:\.\d{1,6})?$/.test(text))
    throw new Error('Введите неотрицательное число: до 14 цифр и 6 знаков после запятой.')
  return text.replace(/^0+(?=\d)/, '')
}
export function scaled(value) {
  const [integer, fraction = ''] = (normalizeDecimal(value) || '0').split('.')
  return BigInt(integer) * SCALE + BigInt(fraction.padEnd(6, '0'))
}
export function decimal(value) {
  return `${value / SCALE}.${String(value % SCALE).padStart(6, '0')}`.replace(/\.?0+$/, '') || '0'
}
export function stepDecimal(value, step, direction, min = '0', max) {
  let next = scaled(value) + BigInt(direction) * scaled(step)
  if (next < scaled(min)) next = scaled(min)
  if (max !== undefined && max !== Infinity && next > scaled(max)) next = scaled(max)
  return decimal(next)
}
export const unitLabel = (code) =>
  ({
    pcs: 'шт.',
    pair: 'пар',
    kg: 'кг',
    g: 'г',
    mg: 'мг',
    l: 'л',
    ml: 'мл',
    m: 'м',
    cm: 'см',
    pack: 'уп.',
    package: 'уп.',
    tablet: 'табл.',
    capsule: 'капс.',
  })[code] ||
  code ||
  ''
export const displayDecimal = (value) =>
  value == null
    ? ''
    : String(value)
        .replace(/(\.\d*?)0+$/, '$1')
        .replace(/\.$/, '')
        .replace('.', ',')
export function formatPairs(pieces) {
  const amount = scaled(pieces)
  const pairs = amount / (2n * SCALE)
  const rest = amount % (2n * SCALE)
  const ending =
    pairs % 100n >= 11n && pairs % 100n <= 14n
      ? 'пар'
      : pairs % 10n === 1n
        ? 'пара'
        : pairs % 10n >= 2n && pairs % 10n <= 4n
          ? 'пары'
          : 'пар'
  return pairs === 0n && rest > 0n
    ? `${displayDecimal(decimal(rest))} шт.`
    : `${pairs} ${ending}${rest ? ` + ${displayDecimal(decimal(rest))} шт.` : ''}`
}
export function formatQuantity(item) {
  if (item.tracking_mode === 'untracked') return 'Учёт присутствия'
  const known = item.known_quantity
  const unknown = item.has_unknown_quantity
  if (known == null || (unknown && scaled(known) === 0n)) return 'Количество неизвестно'
  let text = `${displayDecimal(known)} ${unitLabel(item.base_unit_id || item.unit_code)}`
  if (item.quantity_display && scaled(known) > 0n) {
    text = formatPairs(known)
  }
  if (item.is_estimated) text = `Примерно ${text}`
  if (unknown) text += '; ещё есть неуточнённый остаток'
  else if (item.depleted) text += ' — закончилось'
  return text.trim()
}
export function formatBalance(balance, unit, countingUnit) {
  if (balance.quantity_state === 'not_applicable') return 'Учёт присутствия'
  if (balance.quantity_state === 'unknown') return 'Количество неизвестно'
  const amount =
    unit === 'pcs' && countingUnit === 'pair'
      ? formatPairs(balance.quantity)
      : `${displayDecimal(balance.quantity)} ${unitLabel(unit)}`
  return `${balance.quantity_state === 'estimated' ? 'Примерно ' : ''}${amount}`
}
