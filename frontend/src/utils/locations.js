export function descendants(items, id) {
  const result = new Set([id])
  for (let previous = -1; previous !== result.size;) {
    previous = result.size
    for (const item of items) if (result.has(item.parent_id)) result.add(item.id)
  }
  return result
}
export const isSystemLocation = (location) =>
  location.kind === 'system_unspecified' || location.is_system
export function canMoveLocation(items, source, target) {
  const from = items.find((item) => item.id === source)
  const to = items.find((item) => item.id === target)
  return (
    !!from &&
    !isSystemLocation(from) &&
    from.parent_id !== target &&
    (!target || (!!to && !isSystemLocation(to) && !descendants(items, source).has(target)))
  )
}
