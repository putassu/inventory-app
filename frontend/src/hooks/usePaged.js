import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api/client'
export function usePaged(path) {
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState({ path, items: [], loading: true, error: null })
  const request = useRef(null)
  const currentPath = useRef(path)
  useEffect(() => {
    currentPath.current = path
    const controller = new AbortController()
    request.current = controller
    api(path, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setState({ ...data, path, loading: false, error: null })
      })
      .catch((error) => {
        if (error.name !== 'AbortError') setState({ path, items: [], loading: false, error })
      })
    return () => {
      controller.abort()
      request.current?.abort()
    }
  }, [path, revision])
  const reload = useCallback(() => setRevision((value) => value + 1), [])
  async function more() {
    if (!state.next_cursor || state.loading) return
    const controller = new AbortController()
    request.current = controller
    setState((previous) => ({ ...previous, loading: true, error: null }))
    try {
      const data = await api(
        `${path}${path.includes('?') ? '&' : '?'}cursor=${encodeURIComponent(state.next_cursor)}`,
        { signal: controller.signal },
      )
      if (currentPath.current === path && !controller.signal.aborted)
        setState((previous) => ({
          ...data,
          path,
          items: [...previous.items, ...data.items],
          loading: false,
        }))
    } catch (error) {
      if (error.name !== 'AbortError')
        setState((previous) => ({ ...previous, loading: false, error }))
    }
  }
  return { ...(state.path === path ? state : { items: [], loading: true }), reload, more }
}
