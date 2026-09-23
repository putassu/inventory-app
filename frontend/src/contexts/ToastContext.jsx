import { createContext, useContext, useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { onScopeChanged } from '../api/client'
const ToastContext = createContext(null)
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Set())
  useEffect(() => onScopeChanged(() => setToasts([])), [])
  useEffect(() => () => timers.current.forEach(clearTimeout), [])
  const removeToast = useCallback(
    (id) => setToasts((rows) => rows.filter((row) => row.id !== id)),
    [],
  )
  const addToast = useCallback(
    (message, type = 'info', options = {}) => {
      const id = crypto.randomUUID()
      setToasts((rows) => [...rows, { id, message, type }])
      const timer = setTimeout(
        () => {
          timers.current.delete(timer)
          removeToast(id)
        },
        options.duration || (type === 'error' ? 10000 : 5000),
      )
      timers.current.add(timer)
    },
    [removeToast],
  )
  const value = useMemo(
    () => ({
      addToast,
      toast: (message, options) => addToast(message, 'info', options),
      success: (message, options) => addToast(message, 'success', options),
      error: (message, options) => addToast(message, 'error', options),
      warning: (message, options) => addToast(message, 'warning', options),
    }),
    [addToast],
  )
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <div className={`card toast toast-${toast.type}`} key={toast.id}>
            <span>{toast.message}</span>
            <button
              type="button"
              aria-label="Закрыть уведомление"
              onClick={() => removeToast(toast.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
export const useToast = () => useContext(ToastContext)
