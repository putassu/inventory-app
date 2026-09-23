import { apiCall } from './client'

/**
 * Создает новую задачу
 * @param {Object} payload
 * @param {string} payload.client_request_id UUID запроса
 * @param {string} payload.input_mode "text" | "photo" | "audio" | "photo_audio" | "manual"
 * @param {string} [payload.text] Текст
 * @param {string[]} [payload.media_ids] Массив UUID медиа файлов
 * @param {string} [payload.audio_media_id] UUID аудио файла
 * @param {Object} payload.context Контекст { location_id?: string, item_id?: string }
 * @param {Object} payload.privacy Политика { force_local: boolean }
 * @returns {Promise<Object>} Данные созданной задачи
 */
export async function createTask(payload) {
  return await apiCall('/tasks', {
    method: 'POST',
    body: payload,
  })
}

/**
 * Получает список задач
 * @param {Object} params Параметры запроса (limit, cursor, status)
 * @returns {Promise<Object>} Страница с задачами { items: [], next_cursor: ... }
 */
export async function getTasks(params = {}) {
  const query = new URLSearchParams()
  if (params.limit) query.set('limit', params.limit)
  if (params.cursor) query.set('cursor', params.cursor)
  if (params.status) query.set('status', params.status)

  const queryString = query.toString()
  return await apiCall(`/tasks${queryString ? `?${queryString}` : ''}`)
}

/**
 * Опрашивает статусы задач
 * @param {Array<{task_id: string, status_version: number}>} tasks Список задач для поллинга
 * @returns {Promise<Object>} Ответ поллинга { changed: [], unchanged: [], poll_after_ms: number }
 */
export async function pollTasksStatus(tasks, signal) {
  return await apiCall('/tasks/status', {
    method: 'POST',
    body: { tasks },
    signal,
  })
}
