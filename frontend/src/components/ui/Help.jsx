import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export function Help({ title, children }) {
  const id = useId()
  const button = useRef(null)
  const popup = useRef(null)
  const pinned = useRef(false)
  const timer = useRef(null)
  const [position, setPosition] = useState(null)
  const close = () => {
    pinned.current = false
    setPosition(null)
  }
  function show() {
    clearTimeout(timer.current)
    const rect = button.current.getBoundingClientRect()
    const width = Math.min(440, window.innerWidth - 24)
    const top = Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - 240))
    setPosition({
      left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
      top,
      width,
      maxHeight: window.innerHeight - top - 12,
    })
  }
  function leave() {
    if (!pinned.current) timer.current = setTimeout(() => setPosition(null), 160)
  }
  useEffect(() => {
    if (!position) return
    const outside = (event) => {
      if (!button.current?.contains(event.target) && !popup.current?.contains(event.target)) close()
    }
    const escape = (event) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('resize', close)
    }
  }, [position])
  useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <>
      <button
        ref={button}
        type="button"
        className="help-button"
        aria-label={`Справка: ${title}`}
        aria-expanded={!!position}
        aria-controls={position ? id : undefined}
        aria-describedby={position ? id : undefined}
        onPointerEnter={(event) => {
          if (event.pointerType !== 'touch') show()
        }}
        onPointerLeave={leave}
        onFocus={show}
        onBlur={leave}
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          pinned.current = !pinned.current
          if (pinned.current) show()
          else setPosition(null)
        }}
      >
        <span aria-hidden="true">i</span>
      </button>
      {position &&
        createPortal(
          <div
            ref={popup}
            id={id}
            role="tooltip"
            className="help-popup"
            style={position}
            onPointerEnter={() => clearTimeout(timer.current)}
            onPointerLeave={leave}
          >
            <strong>{title}</strong>
            <div className="help-content">{children}</div>
          </div>,
          document.body,
        )}
    </>
  )
}
