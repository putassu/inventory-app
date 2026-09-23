import { useState } from 'react'
import { ChevronRight, ChevronDown } from 'lucide-react'
import { canMoveLocation, isSystemLocation } from '../../utils/locations'
export function TreeView({ items, renderItem, onMove, busy = false, search = '' }) {
  const [collapsed, setCollapsed] = useState(new Set())
  const [dragged, setDragged] = useState(null)
  const [target, setTarget] = useState(undefined)
  const byId = new Map(items.map((item) => [item.id, item]))
  const children = new Map()
  for (const item of items) {
    const parent = byId.has(item.parent_id) && item.parent_id !== item.id ? item.parent_id : null
    children.set(parent, [...(children.get(parent) || []), item])
  }
  const visible = new Set()
  for (const item of items) {
    if (
      !`${item.name} ${item.full_path} ${item.description || ''}`
        .toLowerCase()
        .includes(search.toLowerCase())
    )
      continue
    let current = item
    const seen = new Set()
    while (current && !seen.has(current.id)) {
      visible.add(current.id)
      seen.add(current.id)
      current = byId.get(current.parent_id)
    }
  }
  function dropProps(id) {
    const allowed = !busy && canMoveLocation(items, dragged, id)
    return {
      onDragOver: (event) => {
        event.stopPropagation()
        if (allowed) {
          event.preventDefault()
          event.dataTransfer.dropEffect = 'move'
          setTarget(id)
        }
      },
      onDragLeave: (event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setTarget(undefined)
      },
      onDrop: async (event) => {
        event.preventDefault()
        event.stopPropagation()
        setTarget(undefined)
        const source = event.dataTransfer.getData('application/x-inventory-location')
        setDragged(null)
        if (busy || !canMoveLocation(items, source, id)) return
        const moved = await onMove(source, id)
        if (moved)
          setCollapsed((previous) => {
            const next = new Set(previous),
              seen = new Set()
            let parent = byId.get(id)
            while (parent && !seen.has(parent.id)) {
              seen.add(parent.id)
              next.delete(parent.id)
              parent = byId.get(parent.parent_id)
            }
            return next
          })
      },
    }
  }
  function node(item, depth = 0, ancestors = new Set()) {
    if (!visible.has(item.id) || ancestors.has(item.id)) return null
    const nested = children.get(item.id) || []
    const expanded = !!search || !collapsed.has(item.id)
    return (
      <li key={item.id}>
        <div
          className={`tree-row ${target === item.id ? 'drop-target' : ''}`}
          {...dropProps(item.id)}
          draggable={!busy && !isSystemLocation(item)}
          onDragStart={(event) => {
            event.stopPropagation()
            event.dataTransfer.setData('application/x-inventory-location', item.id)
            event.dataTransfer.effectAllowed = 'move'
            setDragged(item.id)
          }}
          onDragEnd={() => {
            setDragged(null)
            setTarget(undefined)
          }}
        >
          {nested.length > 0 ? (
            <button
              className="tree-toggle"
              type="button"
              aria-expanded={expanded}
              aria-label={`${expanded ? 'Свернуть' : 'Развернуть'} ${item.name}`}
              onClick={() =>
                setCollapsed((previous) => {
                  const next = new Set(previous)
                  if (next.has(item.id)) next.delete(item.id)
                  else next.add(item.id)
                  return next
                })
              }
            >
              {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
            </button>
          ) : (
            <span className="tree-spacer" />
          )}
          <div className="tree-content">{renderItem(item)}</div>
        </div>
        {!!nested.length && expanded && (
          <ul className="tree-children" style={{ marginLeft: depth < 5 ? undefined : 0 }}>
            {nested.map((child) => node(child, depth + 1, new Set([...ancestors, item.id])))}
          </ul>
        )}
      </li>
    )
  }
  return (
    <div>
      <div className={`root-drop ${target === null ? 'drop-target' : ''}`} {...dropProps(null)}>
        Перетащите сюда для переноса на верхний уровень. На телефоне используйте «Переместить».
      </div>
      <ul className="location-tree">{(children.get(null) || []).map((item) => node(item))}</ul>
      {!visible.size && <p>Места не найдены.</p>}
    </div>
  )
}
