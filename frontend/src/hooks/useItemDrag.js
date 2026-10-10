import { useEffect, useState } from 'react'
import { api } from '../api/client'

const TYPE = 'application/x-inventory-item'

export function useItemDrag(disabled = false) {
  const [target, setTarget] = useState(null)
  const [merge, setMerge] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const clear = () => setTarget(null)
    document.addEventListener('dragend', clear, true)
    document.addEventListener('drop', clear, true)
    return () => {
      document.removeEventListener('dragend', clear, true)
      document.removeEventListener('drop', clear, true)
    }
  }, [])
  function dragProps(item) {
    const enabled = !disabled && !merge && (!item.lifecycle || item.lifecycle === 'active')
    return {
      draggable: enabled,
      'data-drop-target': target === item.id,
      onDragStart(event) {
        event.stopPropagation()
        if (!enabled) {
          event.preventDefault()
          return
        }
        event.dataTransfer.setData(TYPE, item.id)
        event.dataTransfer.effectAllowed = 'move'
        setError('')
      },
      onDragOver(event) {
        if (!enabled || ![...event.dataTransfer.types].includes(TYPE)) return
        event.preventDefault()
        event.stopPropagation()
        event.dataTransfer.dropEffect = 'move'
        setTarget(item.id)
      },
      onDragLeave(event) {
        if (!event.currentTarget.contains(event.relatedTarget)) setTarget(null)
      },
      async onDrop(event) {
        const sourceId = event.dataTransfer.getData(TYPE)
        if (!enabled || !sourceId) return
        event.preventDefault()
        event.stopPropagation()
        if (sourceId === item.id) return
        setError('')
        try {
          setMerge([await api(`/items/${sourceId}`), item])
        } catch (cause) {
          setError(cause.message)
        }
      },
    }
  }
  return { dragProps, merge, setMerge, error }
}
