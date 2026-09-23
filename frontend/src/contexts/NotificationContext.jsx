import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

const NotificationContext = createContext(null)
export function NotificationProvider({ children }) {
  const [notifications, setNotifications] = useState([])
  const [error, setError] = useState('')
  const refreshNotifications = useCallback(async () => {
    const data = await api('/notifications?limit=50')
    setNotifications(data.items)
  }, [])
  useEffect(() => {
    let active = true
    let timer
    const controller = new AbortController()
    async function poll() {
      try {
        const data = await api('/notifications?limit=50', { signal: controller.signal })
        if (active) {
          setNotifications(data.items)
          setError('')
        }
      } catch (cause) {
        if (active && cause.name !== 'AbortError') setError(cause.message)
      }
      if (active) timer = setTimeout(poll, 60000)
    }
    void poll()
    return () => {
      active = false
      clearTimeout(timer)
      controller.abort()
    }
  }, [])
  return (
    <NotificationContext.Provider
      value={{
        notifications,
        unreadCount: notifications.filter((row) => !row.read_at).length,
        error,
        refreshNotifications,
      }}
    >
      {children}
    </NotificationContext.Provider>
  )
}
export const useNotifications = () => useContext(NotificationContext)
