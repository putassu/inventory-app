import { apiCall } from './client'

/**
 * Загружает медиафайл (фото или аудио) на сервер.
 * @param {File} file Файл (уже сжатый или сконвертированный)
 * @param {string} privacyPolicy Политика приватности (local_only или cloud_allowed)
 * @param {boolean} clientPreprocessed Был ли файл предварительно обработан на клиенте (ресайз/WAV конвертация)
 * @returns {Promise<Object>} Данные ответа сервера, например { media_id: "...", type: "image", state: "..." }
 */
export async function uploadMedia(
  file,
  privacyPolicy = 'local_only',
  clientPreprocessed = true,
  key = crypto.randomUUID(),
) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('privacy_policy', privacyPolicy)
  formData.append('client_preprocessed', clientPreprocessed.toString())

  // apiCall автоматически использует токен и обрабатывает ошибки
  const response = await apiCall('/media', {
    method: 'POST',
    key,
    body: formData,
    // Важно: не устанавливаем Content-Type, браузер сам поставит multipart/form-data и границу (boundary)
    headers: {
      Accept: 'application/json',
    },
  })

  return response
}
