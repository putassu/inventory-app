import { randomId } from '../utils/id'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useBlocker, useNavigate, useSearchParams } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { MediaCapture } from '../components/ui/MediaCapture'
import { Modal } from '../components/ui/Modal'
import { uploadMedia } from '../api/media'
import { api } from '../api/client'
import { useTasks } from '../contexts/TaskContext'
import { useResource } from '../hooks/useResource'
import { ReceiveStockModal } from '../components/operations/ReceiveStockModal'
import { getCaptureDraft, clearCaptureDraft } from '../utils/captureDraft'

export function Capture() {
  const [params] = useSearchParams()
  const [draft] = useState(getCaptureDraft)
  useEffect(clearCaptureDraft, [])
  const [text, setText] = useState(draft?.text || '')
  const [manual, setManual] = useState(false)
  const [photos, setPhotos] = useState(draft?.photos || [])
  const [audio, setAudio] = useState(null)
  const [locationId, setLocationId] = useState(params.get('location_id') || '')
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [mediaBusy, setMediaBusy] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const [modelPreference, setModelPreference] = useState('local')
  const uploads = useRef(new Map())
  const attempt = useRef(null)
  const lock = useRef(false)
  const submitted = useRef(false)
  const dirty = !!(text.trim() || photos.length || audio || mediaBusy)
  const blocker = useBlocker(() => dirty && !submitted.current)
  useEffect(() => {
    if (!dirty) return
    const warn = (event) => {
      if (!submitted.current) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    const scope = (event) => {
      if (
        !submitted.current &&
        !window.confirm('Есть неотправленные материалы. Покинуть страницу и потерять их?')
      )
        event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    window.addEventListener('inventory:before-scope-change', scope)
    return () => {
      window.removeEventListener('beforeunload', warn)
      window.removeEventListener('inventory:before-scope-change', scope)
    }
  }, [dirty])
  const { addTask } = useTasks()
  const { data: locations } = useResource('/locations')
  const { data: capabilities } = useResource('/capabilities')
  const { data: contextItem } = useResource(
    params.get('item_id') ? `/items/${params.get('item_id')}` : null,
  )
  const limits = capabilities?.media_limits || { max_images: 3, max_audio_seconds: 60 }
  const onMediaCaptured = useCallback((media) => {
    if (media.type === 'photo') setPhotos(media.files)
    else setAudio(media.file)
  }, [])
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
      if (photos.length > limits.max_images)
        throw new Error(`Можно отправить не больше ${limits.max_images} фото за одну задачу.`)
      if (audio?.durationSeconds > limits.max_audio_seconds)
        throw new Error(`Обрежьте запись до ${limits.max_audio_seconds} секунд перед отправкой.`)
      const files = [...photos, ...(audio ? [audio] : [])]
      if (limits.max_file_bytes && files.some((file) => file.size > limits.max_file_bytes))
        throw new Error(
          'Подготовленный файл превышает лимит сервера. Уменьшите фото или обрежьте запись.',
        )
      if (
        limits.max_task_bytes &&
        files.reduce((sum, file) => sum + file.size, 0) > limits.max_task_bytes
      )
        throw new Error(
          'Материалы превышают размер одной задачи. Отправьте их несколькими задачами.',
        )
      const ids = []
      for (const [index, file] of [...photos, ...(audio ? [audio] : [])].entries()) {
        setProgress(`Загрузка файла ${index + 1} из ${photos.length + (audio ? 1 : 0)}`)
        if (!uploads.current.has(file)) uploads.current.set(file, {})
        const cache = uploads.current.get(file)
        const entry = (cache[modelPreference] ||= { key: randomId() })
        entry.media ||= await uploadMedia(
          file,
          modelPreference === 'cloud' ? 'cloud_allowed' : 'local_only',
          true,
          entry.key,
        )
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
        privacy: { force_local: modelPreference === 'local', model_preference: modelPreference },
      }
      const signature = JSON.stringify(body)
      if (attempt.current?.signature !== signature)
        attempt.current = {
          signature,
          key: randomId(),
          body: { ...body, client_request_id: randomId() },
        }
      setProgress('Создание задачи…')
      const task = await api('/tasks', {
        method: 'POST',
        key: attempt.current.key,
        body: attempt.current.body,
      })
      addTask(task)
      submitted.current = true
      navigate(locationId ? `/locations/${locationId}` : '/items')
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
      <div className="toolbar">
        <h1>Добавить по фото или голосу</h1>
        <Button
          variant="secondary"
          disabled={busy || mediaBusy || uncertain || (!!params.get('item_id') && !contextItem)}
          onClick={() => setManual(true)}
        >
          Заполнить вручную
        </Button>
      </div>
      {manual && (
        <ReceiveStockModal
          isOpen
          initialLocationId={locationId}
          initialName={text}
          initialPhotos={photos}
          item={contextItem}
          showCaptureLink={false}
          locations={locations?.items || []}
          onClose={() => setManual(false)}
          onSuccess={() => {
            submitted.current = true
            navigate(locationId ? `/locations/${locationId}` : '/items')
          }}
        />
      )}
      {blocker.state === 'blocked' && (
        <Modal isOpen title="Неотправленные материалы" onClose={() => blocker.reset()}>
          <p>
            {uncertain
              ? 'Сервер мог принять задачу. После выхода проверьте список задач перед повторной отправкой.'
              : 'Фото, запись и текст этой формы будут потеряны. Покинуть страницу?'}
          </p>
          <div className="actions">
            <Button onClick={() => blocker.reset()}>Остаться</Button>
            <Button variant="danger" onClick={() => blocker.proceed()}>
              Покинуть страницу
            </Button>
          </div>
        </Modal>
      )}
      {contextItem && (
        <p className="notice">
          Материалы для вещи: <strong>{contextItem.name}</strong>
        </p>
      )}
      <p>
        Новая вещь появится сразу. Распознанные сведения можно проверить позже. Изменения
        существующих вещей требуют подтверждения.
      </p>
      {capabilities?.ai_processing_paused && (
        <p className="notice">
          Распознавание сейчас приостановлено. Отправленная вещь будет ждать в каталоге; вручную
          можно сохранить её сразу.
        </p>
      )}
      {capabilities && !capabilities.audio_inference && (
        <p className="notice">
          Распознавание аудио сейчас недоступно на сервере. Можно отправить текст или фото.
        </p>
      )}
      <form className="page-stack" onSubmit={submit}>
        <Select
          label="Модель распознавания"
          value={modelPreference}
          disabled={busy || uncertain}
          info="Локальная — модель на доверенном сервере владельца. При выборе облака первичная проверка всё равно выполняется локально. Документы, чувствительные данные и материалы с неопределённой приватностью остаются локально. Запрет облака у вещи или места также сохраняется. Ключ провайдера хранится только на сервере."
          onChange={(event) => {
            setModelPreference(event.target.value)
            setError('')
          }}
        >
          <option value="local">Локальная — доверенный сервер</option>
          <option
            value="cloud"
            disabled={!capabilities?.cloud_configured || !capabilities?.external_enabled}
          >
            Облачная — после проверки приватности
          </option>
        </Select>
        {capabilities && (!capabilities.cloud_configured || !capabilities.external_enabled) && (
          <small>Облачная модель пока не подключена администратором.</small>
        )}
        <MediaCapture
          initialPhotos={draft?.photos || []}
          maxPhotos={limits.max_images}
          maxAudioSeconds={limits.max_audio_seconds}
          onBusyChange={setMediaBusy}
          disabled={busy || uncertain}
          onMediaCaptured={onMediaCaptured}
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
          {busy ? 'Отправка…' : 'Добавить и распознать'}
        </Button>
      </form>
    </section>
  )
}
