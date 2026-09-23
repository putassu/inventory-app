import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
export function Modal({ isOpen, onClose, title, children, footer, busy = false }) {
  const dialog = useRef(null)
  const titleId = useId()
  useEffect(() => {
    if (!isOpen) return
    const previous = document.activeElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const element = dialog.current
    element.showModal()
    return () => {
      element.close()
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [isOpen])
  if (!isOpen) return null
  return createPortal(
    <dialog
      ref={dialog}
      className="app-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onClose()
      }}
    >
      <div className="toolbar">
        <h2 id={titleId}>{title}</h2>
        <button type="button" disabled={busy} aria-label="Закрыть окно" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="dialog-body">{children}</div>
      {footer && <div className="toolbar dialog-footer">{footer}</div>}
    </dialog>,
    document.body,
  )
}
