import { useRef, useState } from 'react'
import { write } from '../api/client'
export function useMutation() {
  const attempt = useRef(null)
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  async function run(path, body = {}, method = 'POST') {
    if (attempt.current?.running) return null
    const signature = JSON.stringify([path, body, method])
    if (attempt.current?.signature !== signature)
      attempt.current = { signature, key: crypto.randomUUID() }
    const current = attempt.current
    current.running = true
    setBusy(true)
    setError('')
    try {
      const result = await write(path, body, method, current.key)
      attempt.current = null
      return result
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
      if (e.status >= 400 && e.status < 500 && e.status !== 429) attempt.current = null
      return null
    } finally {
      current.running = false
      setBusy(false)
    }
  }
  return { run, busy, error }
}
