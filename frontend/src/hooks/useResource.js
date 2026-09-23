import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

export function useResource(path) {
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState({ data: null, loading: true, error: null, path })
  const reload = useCallback(() => setRevision((n) => n + 1), [])
  useEffect(() => {
    if (!path) return
    const controller = new AbortController()
    api(path, { signal: controller.signal }).then(
      (data) => setState({ data, loading: false, error: null, path }),
      (error) => {
        if (error.name !== 'AbortError')
          setState((previous) => ({
            data: previous.path === path ? previous.data : null,
            loading: false,
            error,
            path,
          }))
      },
    )
    return () => controller.abort()
  }, [path, revision])
  return { ...(state.path === path ? state : { data: null, loading: true, error: null }), reload }
}
