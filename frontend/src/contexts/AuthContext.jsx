import { createContext, useContext, useState, useEffect } from 'react'
import { api, setSession, clearSession, restoreSession, onSessionExpired } from '../api/client'

const AuthContext = createContext(null)
function initialScope(user) {
  const saved = localStorage.getItem(`inventory-workspace:${user.id}`)
  return (
    user.workspaces?.find((workspace) => workspace.id === saved) || user.workspaces?.[0] || null
  )
}
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [activeWorkspace, setActiveWorkspace] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  useEffect(() => {
    let active = true
    const unsubscribe = onSessionExpired(() => {
      setUser(null)
      setActiveWorkspace(null)
    })
    restoreSession()
      .then((data) => {
        if (!active) return
        const workspace = initialScope(data)
        setSession(undefined, workspace?.id || null, data.id)
        setUser(data)
        setActiveWorkspace(workspace)
      })
      .catch(() => {})
      .finally(() => {
        if (active) setIsLoading(false)
      })
    return () => {
      active = false
      unsubscribe()
    }
  }, [])
  async function login(loginName, password) {
    clearSession()
    const data = await api('/auth/login', {
      method: 'POST',
      body: { login: loginName, password, client_type: 'web' },
    })
    setSession(data.access_token, null)
    const profile = await api('/me')
    const workspace = initialScope(profile)
    setSession(undefined, workspace?.id || null, profile.id)
    setUser(profile)
    setActiveWorkspace(workspace)
  }
  async function logout(all = false) {
    if (!window.dispatchEvent(new Event('inventory:before-scope-change', { cancelable: true })))
      return
    try {
      await api(all ? '/auth/logout-all' : '/auth/logout', { method: 'POST' })
    } finally {
      clearSession()
      setUser(null)
      setActiveWorkspace(null)
    }
  }
  function selectWorkspace(workspace) {
    if (!user.workspaces.some((row) => row.id === workspace.id)) return
    if (workspace.id === activeWorkspace?.id) return
    if (!window.dispatchEvent(new Event('inventory:before-scope-change', { cancelable: true })))
      return
    setSession(undefined, workspace.id)
    localStorage.setItem(`inventory-workspace:${user.id}`, workspace.id)
    setActiveWorkspace(workspace)
  }
  return (
    <AuthContext.Provider
      value={{
        user,
        workspaces: user?.workspaces || [],
        activeWorkspace,
        isLoading,
        login,
        logout,
        selectWorkspace,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
export const useAuth = () => useContext(AuthContext)
