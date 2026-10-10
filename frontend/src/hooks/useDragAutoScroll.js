import { useEffect } from 'react'

// Прокручиваем ближайшую доступную область, пока указатель удерживается у её края.
export function useDragAutoScroll() {
  useEffect(() => {
    let point = null,
      frame = 0,
      previous = 0,
      dragging = false
    const stop = () => {
      cancelAnimationFrame(frame)
      point = null
      frame = previous = 0
    }
    const finish = () => {
      dragging = false
      stop()
    }
    const start = () => {
      stop()
      dragging = true
    }
    function tick(time) {
      const elapsed = Math.min(40, previous ? time - previous : 16)
      previous = time
      let element = document.elementFromPoint(point.x, point.y)
      while (element) {
        const root = element === document.scrollingElement
        const box = root ? { top: 0, bottom: window.innerHeight } : element.getBoundingClientRect()
        const top = Math.max(0, box.top),
          bottom = Math.min(window.innerHeight, box.bottom)
        const edge = Math.min(80, (bottom - top) / 3)
        const speed =
          point.y < top + edge
            ? -Math.min(1, (top + edge - point.y) / edge)
            : point.y > bottom - edge
              ? Math.min(1, (point.y - bottom + edge) / edge)
              : 0
        const scrollable = root || /auto|scroll/.test(getComputedStyle(element).overflowY)
        if (scrollable && speed && element.scrollHeight > element.clientHeight) {
          const before = element.scrollTop
          // CSS smooth не должен продолжать движение после отпускания мыши.
          element.scrollTo({ top: before + speed * elapsed * 0.8, behavior: 'instant' })
          if (element.scrollTop !== before) break
        }
        element = element.parentElement
      }
      frame = requestAnimationFrame(tick)
    }
    const over = (event) => {
      if (!dragging) return
      if (
        ![...(event.dataTransfer?.types || [])].some((type) =>
          ['application/x-inventory-location', 'application/x-inventory-item'].includes(type),
        )
      )
        return
      if (
        event.clientX < 0 ||
        event.clientY < 0 ||
        event.clientX >= window.innerWidth ||
        event.clientY >= window.innerHeight
      )
        return stop()
      point = { x: event.clientX, y: event.clientY }
      if (!frame) frame = requestAnimationFrame(tick)
    }
    const leave = (event) => {
      if (!event.relatedTarget) stop()
    }
    const escape = (event) => {
      if (event.key === 'Escape') finish()
    }
    document.addEventListener('dragstart', start, true)
    document.addEventListener('dragover', over, true)
    document.addEventListener('dragleave', leave, true)
    document.addEventListener('drop', finish, true)
    document.addEventListener('dragend', finish, true)
    document.addEventListener('mouseup', finish, true)
    document.addEventListener('keydown', escape, true)
    window.addEventListener('blur', finish)
    return () => {
      stop()
      document.removeEventListener('dragstart', start, true)
      document.removeEventListener('dragover', over, true)
      document.removeEventListener('dragleave', leave, true)
      document.removeEventListener('drop', finish, true)
      document.removeEventListener('dragend', finish, true)
      document.removeEventListener('mouseup', finish, true)
      document.removeEventListener('keydown', escape, true)
      window.removeEventListener('blur', finish)
    }
  }, [])
}
