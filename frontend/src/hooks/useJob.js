import { useEffect } from 'react'
import { useResource } from './useResource'
export function useJob(path) {
  const resource = useResource(path)
  const { data, reload } = resource
  useEffect(() => {
    if (
      !path ||
      ['succeeded', 'failed', 'cancelled', 'expired', 'revoked', 'partially_completed'].includes(
        data?.status,
      )
    )
      return
    const timer = setTimeout(reload, 2500)
    return () => clearTimeout(timer)
  }, [path, data, reload])
  return resource
}
