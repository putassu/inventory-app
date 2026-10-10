import { useEffect, useState } from 'react'
import { api } from '../api/client'

export function ProcessingStatus() {
  const [status, setStatus] = useState(null)
  useEffect(() => {
    const controller = new AbortController()
    let timer
    async function poll() {
      if (!document.hidden) {
        try {
          setStatus(await api('/processing-status', { signal: controller.signal }))
        } catch {
          // Сетевые ошибки показываются в соответствующем действии пользователя.
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 10000)
    }
    void poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [])
  if (!status || status.recognition_available) return null
  return (
    <aside className="notice" role="status">
      {!status.saving_available
        ? 'Сервис сохранения временно недоступен. Принятые операции сохранятся после его восстановления. Повторять добавление не нужно.'
        : status.gpu_state === 'quarantined'
          ? 'Приложение приостановило распознавание: завершение предыдущего запроса к модели не подтверждено. Администратор может проверить запрос и возобновить обработку. Вещи и фотографии можно добавлять вручную.'
          : 'Распознавание временно недоступно. Можно добавлять вещи и фотографии вручную.'}
    </aside>
  )
}
