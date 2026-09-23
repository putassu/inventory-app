import { useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { MediaCapture } from '../components/ui/MediaCapture'
import { uploadMedia } from '../api/media'
import { api } from '../api/client'
import { useTasks } from '../contexts/TaskContext'
import { useResource } from '../hooks/useResource'

export function Capture() {
  const [params] = useSearchParams()
  const [text, setText] = useState('')
  const [photos, setPhotos] = useState([])
  const [audio, setAudio] = useState(null)
  const [locationId, setLocationId] = useState(params.get('location_id') || '')
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [mediaBusy, setMediaBusy] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const uploads = useRef(new Map())
  const attempt = useRef(null)
  const lock = useRef(false)
  const { addTask } = useTasks()
  const { data: locations } = useResource('/locations')
  const { data: capabilities } = useResource('/capabilities')
  const navigate = useNavigate()
  async function submit(event) {
    event.preventDefault()
    if (lock.current || mediaBusy) return
    lock.current = true
    setBusy(true)
    setError('')
    try {
      if (!text.trim() && !photos.length && !audio)
        throw new Error('Добавьте текст, фото или аудио.')
      const ids = []
      for (const [index, file] of [...photos, ...(audio ? [audio] : [])].entries()) {
        setProgress(`Загрузка файла ${index + 1} из ${photos.length + (audio ? 1 : 0)}`)
        if (!uploads.current.has(file)) uploads.current.set(file, { key: crypto.randomUUID() })
        const entry = uploads.current.get(file)
        entry.media ||= await uploadMedia(file, 'local_only', true, entry.key)
        ids.push(entry.media.media_id)
      }
      const body = {
        input_mode: audio
          ? photos.length
            ? 'photo_audio'
            : 'audio'
          : photos.length
            ? 'photo'
            : 'text',
        text: text.trim() || null,
        media_ids: ids.slice(0, photos.length),
        audio_media_id: audio ? ids.at(-1) : null,
        context: { location_id: locationId || null, item_id: params.get('item_id') || null },
        privacy: { force_local: true },
      }
      const signature = JSON.stringify(body)
      if (attempt.current?.signature !== signature)
        attempt.current = {
          signature,
          key: crypto.randomUUID(),
          body: { ...body, client_request_id: crypto.randomUUID() },
        }
      setProgress('Создание задачи…')
      const task = await api('/tasks', {
        method: 'POST',
        key: attempt.current.key,
        body: attempt.current.body,
      })
      addTask(task)
      navigate(`/tasks/${task.task_id}`)
    } catch (cause) {
      setUncertain(!!attempt.current && (!cause.status || cause.status >= 500))
      if (cause.status >= 400 && cause.status < 500 && cause.status !== 429) attempt.current = null
      setError(
        cause.message || 'Ошибка сети. Повторите отправку: уже загруженные файлы сохранятся.',
      )
    } finally {
      setBusy(false)
      lock.current = false
    }
  }
  return (
    <section className="page-stack">
      <h1>Фото, голос или текст</h1>
      <p>Обработка на доверенном сервере. Учёт изменится после вашей проверки и подтверждения.</p>
      {capabilities && !capabilities.audio_inference && (
        <p className="notice">
          Распознавание аудио сейчас недоступно на сервере. Можно отправить текст или фото.
        </p>
      )}
      <form className="page-stack" onSubmit={submit}>
        <MediaCapture
          onBusyChange={setMediaBusy}
          disabled={busy || uncertain}
          onMediaCaptured={(media) => {
            if (media.type === 'photo') setPhotos(media.files)
            else setAudio(media.file)
          }}
        />
        <Input
          label="Что произошло"
          as="textarea"
          rows={4}
          maxLength={16000}
          value={text}
          onChange={(event) => setText(event.target.value)}
          disabled={busy || uncertain}
          placeholder="Например: положил пару носков в белый шкаф"
        />
        <Select
          label="Контекст места"
          disabled={busy || uncertain}
          value={locationId}
          onChange={(event) => setLocationId(event.target.value)}
        >
          <option value="">Не указано</option>
          {locations?.items.map((location) => (
            <option key={location.id} value={location.id}>
              {location.full_path}
            </option>
          ))}
        </Select>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {uncertain && (
          <p className="notice">
            Сервер мог уже принять задачу. Повторите эту же отправку для получения результата:
            данные временно заблокированы от изменения.
          </p>
        )}
        {busy && <p role="status">{progress}</p>}
        <Button type="submit" disabled={busy || mediaBusy}>
          {busy ? 'Отправка…' : 'Подготовить предложение'}
        </Button>
      </form>
    </section>
  )
}
