import { useState, useRef, useEffect, useCallback } from 'react'
import { Button } from './Button'
import { Input } from './Input'
import { Modal } from './Modal'
import { AudioRecorder, compressImage, prepareAudio } from '../../utils/media'
function useBlobUrl(file) {
  const [url, setUrl] = useState(null)
  // URL принадлежит эффекту и освобождается вместе с файлом.
  useEffect(() => {
    if (!file) return
    const value = URL.createObjectURL(file)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUrl(value)
    return () => URL.revokeObjectURL(value)
  }, [file])
  return url
}
function Photo({ file, index, onRemove, onMove, onEdit, disabled }) {
  const url = useBlobUrl(file)
  return (
    <div className="capture-photo">
      <img src={url || undefined} alt={`Фото ${index + 1}`} />
      <div className="toolbar">
        <Button
          variant="text"
          disabled={disabled || !index}
          onClick={onMove}
          aria-label={`Переместить фото ${index + 1} влево`}
        >
          ←
        </Button>
        <Button variant="text" disabled={disabled} onClick={onEdit}>
          Обрезать
        </Button>
        <Button
          variant="text"
          disabled={disabled}
          onClick={onRemove}
          aria-label={`Удалить фото ${index + 1}`}
        >
          ×
        </Button>
      </div>
    </div>
  )
}
function PhotoEditor({ file, onSave, onClose }) {
  const url = useBlobUrl(file)
  const [crop, setCrop] = useState({ x: 0, y: 0, width: 100, height: 100 })
  const [rotation, setRotation] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState(null)
  const previewUrl = useBlobUrl(preview)
  useEffect(() => {
    let active = true
    const timer = setTimeout(() => {
      compressImage(file, 480, { crop, rotation })
        .then((image) => {
          if (active) {
            setPreview(image)
            setError('')
          }
        })
        .catch((cause) => {
          if (active) {
            setPreview(null)
            setError(cause.message)
          }
        })
    }, 200)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [file, crop, rotation])
  return (
    <Modal isOpen onClose={onClose} busy={busy} title="Обрезка и поворот фото">
      <div className="crop-preview">
        <img src={url || undefined} alt="Выбранная область фото" />
        <span
          style={{
            left: `${crop.x}%`,
            top: `${crop.y}%`,
            width: `${crop.width}%`,
            height: `${crop.height}%`,
          }}
        />
      </div>
      <div className="form-grid">
        {Object.entries({
          x: 'Отступ слева, %',
          y: 'Отступ сверху, %',
          width: 'Ширина, %',
          height: 'Высота, %',
        }).map(([key, title]) => (
          <Input
            key={key}
            label={title}
            type="number"
            disabled={busy}
            min="0"
            max="100"
            value={crop[key]}
            onChange={(event) =>
              setCrop((previous) => ({ ...previous, [key]: Number(event.target.value) }))
            }
          />
        ))}
      </div>
      <p>Поворот: {rotation}°</p>
      {preview && previewUrl && (
        <figure className="crop-result">
          <img src={previewUrl} alt="Результат обрезки и поворота" />
          <figcaption>После обрезки и поворота</figcaption>
        </figure>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="toolbar">
        <Button
          disabled={busy}
          variant="secondary"
          onClick={() => setRotation((rotation + 90) % 360)}
        >
          Повернуть на 90°
        </Button>
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              onSave(await compressImage(file, 1600, { crop, rotation }))
            } catch (cause) {
              setError(cause.message)
            } finally {
              setBusy(false)
            }
          }}
        >
          Применить
        </Button>
      </div>
    </Modal>
  )
}
export function MediaCapture({
  onMediaCaptured,
  disabled = false,
  onBusyChange,
  maxPhotos = 3,
  maxAudioSeconds = 60,
  photosOnly = false,
  initialPhotos = [],
}) {
  const [photos, setPhotos] = useState(initialPhotos)
  const [audio, setAudio] = useState(null)
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  const [edit, setEdit] = useState(null)
  const [from, setFrom] = useState('0')
  const [to, setTo] = useState('')
  const recorder = useRef(null)
  const mounted = useRef(true)
  const audioUrl = useBlobUrl(audio)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      recorder.current?.cancel()
    }
  }, [])
  useEffect(() => {
    onBusyChange?.(busy || recording)
  }, [busy, recording, onBusyChange])
  useEffect(() => {
    if (!recording) return
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000)
    return () => clearInterval(timer)
  }, [recording])
  function changePhotos(next) {
    setPhotos(next)
    onMediaCaptured({ type: 'photo', files: next })
  }
  const changeAudio = useCallback(
    (file) => {
      setAudio(file)
      onMediaCaptured({ type: 'audio', file })
    },
    [onMediaCaptured],
  )
  useEffect(() => {
    if (!recording) return
    const stop = setTimeout(
      async () => {
        if (recorder.current?.recorder?.state !== 'recording') return
        setBusy(true)
        try {
          const file = await recorder.current.stop()
          if (mounted.current) changeAudio(file)
        } catch (cause) {
          if (mounted.current) setError(cause.message)
        } finally {
          if (mounted.current) {
            setRecording(false)
            setBusy(false)
          }
        }
      },
      Math.min(maxAudioSeconds, 300) * 1000,
    )
    return () => clearTimeout(stop)
  }, [recording, maxAudioSeconds, changeAudio])
  async function addPhotos(event) {
    const files = [...event.target.files]
    event.target.value = ''
    if (photos.length + files.length > maxPhotos) {
      setError(`Можно прикрепить не больше ${maxPhotos} фотографий к одной задаче.`)
      return
    }
    setBusy(true)
    setError('')
    try {
      const next = [...photos]
      for (const file of files) next.push(await compressImage(file))
      if (mounted.current) changePhotos(next)
    } catch (cause) {
      setError(cause.message)
    } finally {
      if (mounted.current) setBusy(false)
    }
  }
  async function toggleRecording() {
    setBusy(true)
    setError('')
    try {
      if (recording) {
        const file = await recorder.current.stop()
        if (mounted.current) {
          changeAudio(file)
          setRecording(false)
        }
      } else {
        recorder.current = new AudioRecorder()
        await recorder.current.start()
        if (!mounted.current) recorder.current.cancel()
        else {
          setSeconds(0)
          setRecording(true)
        }
      }
    } catch (cause) {
      recorder.current?.cancel()
      setRecording(false)
      setError(
        {
          NotAllowedError:
            'Доступ к микрофону запрещён. Разрешите его в настройках браузера или прикрепите аудиофайл.',
          NotFoundError: 'Микрофон не найден. Подключите его или прикрепите аудиофайл.',
          NotReadableError:
            'Микрофон занят или недоступен. Закройте другие приложения записи и повторите попытку.',
        }[cause.name] ||
          cause.message ||
          'Микрофон недоступен.',
      )
    } finally {
      if (mounted.current) setBusy(false)
    }
  }
  return (
    <div className={photosOnly ? 'page-stack photo-input' : 'page-stack card'}>
      <p className="muted">
        {photosOnly
          ? 'Фото (необязательно)'
          : `До ${maxPhotos} фото и ${Math.min(maxAudioSeconds, 300)} секунд аудио.`}
      </p>
      <div className="toolbar">
        <label className="btn btn-secondary">
          Прикрепить фото
          <input
            aria-label="Прикрепить фото"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            disabled={disabled || busy || recording}
            onChange={addPhotos}
            className="visually-hidden"
          />
        </label>
        <label className="btn btn-secondary">
          Снять фото
          <input
            aria-label="Снять фото"
            type="file"
            accept="image/*"
            capture="environment"
            disabled={disabled || busy || recording}
            onChange={addPhotos}
            className="visually-hidden"
          />
        </label>
        {!photosOnly && (
          <>
            <Button
              variant={recording ? 'danger' : 'secondary'}
              disabled={disabled || busy}
              onClick={toggleRecording}
            >
              {recording ? `Остановить запись (${seconds} с)` : 'Записать голос'}
            </Button>
            <label className="btn btn-secondary">
              Аудиофайл
              <input
                aria-label="Прикрепить аудиофайл"
                type="file"
                accept="audio/*"
                disabled={disabled || busy || recording}
                className="visually-hidden"
                onChange={async (event) => {
                  const file = event.target.files[0]
                  event.target.value = ''
                  if (!file) return
                  setBusy(true)
                  setError('')
                  try {
                    const prepared = await prepareAudio(file)
                    if (mounted.current) changeAudio(prepared)
                  } catch (cause) {
                    setError(cause.message)
                  } finally {
                    setBusy(false)
                  }
                }}
              />
            </label>
          </>
        )}
      </div>
      {busy && <p role="status">Подготовка медиа на устройстве…</p>}
      {recording && (
        <p role="status">
          Микрофон включён. Остановите запись перед отправкой. При уходе со страницы запись будет
          отменена.
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="capture-photos">
        {photos.map((file, index) => (
          <Photo
            key={`${index}:${file.lastModified}`}
            file={file}
            index={index}
            disabled={disabled || busy}
            onRemove={() => changePhotos(photos.filter((_, i) => index !== i))}
            onMove={() => {
              const next = [...photos]
              ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
              changePhotos(next)
            }}
            onEdit={() => setEdit(index)}
          />
        ))}
      </div>
      {audio && (
        <div className="page-stack">
          <p>
            Длительность: {audio.durationSeconds?.toFixed(1)} с
            {audio.durationSeconds > maxAudioSeconds
              ? ` — обрежьте до ${maxAudioSeconds} с перед отправкой`
              : ''}
            .
          </p>
          <audio controls src={audioUrl || undefined} />
          <div className="toolbar">
            <Input
              label="Начало, секунды"
              inputMode="decimal"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
            />
            <Input
              label="Конец, секунды (пусто — до конца)"
              inputMode="decimal"
              value={to}
              onChange={(event) => setTo(event.target.value)}
            />
            <Button
              disabled={disabled || busy}
              onClick={async () => {
                setBusy(true)
                setError('')
                try {
                  changeAudio(
                    await prepareAudio(
                      audio,
                      Number(from.replace(',', '.')),
                      to === '' ? null : Number(to.replace(',', '.')),
                    ),
                  )
                  setFrom('0')
                  setTo('')
                } catch (cause) {
                  setError(cause.message)
                } finally {
                  setBusy(false)
                }
              }}
            >
              Обрезать запись
            </Button>
            <Button variant="text" disabled={disabled || busy} onClick={() => changeAudio(null)}>
              Удалить запись
            </Button>
          </div>
        </div>
      )}
      {edit !== null && (
        <PhotoEditor
          file={photos[edit]}
          onClose={() => setEdit(null)}
          onSave={(file) => {
            changePhotos(photos.map((photo, index) => (index === edit ? file : photo)))
            setEdit(null)
          }}
        />
      )}
    </div>
  )
}
