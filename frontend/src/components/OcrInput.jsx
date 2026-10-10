import { randomId } from '../utils/id'
import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, write } from '../api/client'
import { Button } from './ui/Button'
import { Input } from './ui/Input'
import { StageRing } from './StageRing'

export function OcrInput({ photo, value, onChange, disabled, onBusyChange }) {
  const [task, setTask] = useState(null)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const attempt = useRef(null)
  const lock = useRef(false)
  const active =
    task && ['accepted', 'preparing', 'queued', 'running', 'retry_wait'].includes(task.status)
  const busy = sending || !!active
  const acceptText = useEffectEvent((text) => onChange(text))
  useEffect(() => {
    onBusyChange(busy)
    return () => onBusyChange(false)
  }, [busy, onBusyChange])
  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    let timer
    async function poll() {
      try {
        const updated = await api(`/tasks/${task.task_id}`, { signal: controller.signal })
        if (controller.signal.aborted) return
        setTask(updated)
        if (updated.status === 'succeeded') {
          acceptText(updated.result.ocr_text || '')
          if (!updated.result.ocr_text) setError('Текст не найден. Можно вписать его вручную.')
        } else if (['failed', 'cancelled', 'expired'].includes(updated.status)) {
          if (updated.result?.ocr_text) acceptText(updated.result.ocr_text)
          setError(
            updated.error_code === 'LOCAL_CONNECTION'
              ? 'Сервер приложения не смог подключиться к модели OCR. Фото сохранено. Повторите OCR позже или введите текст вручную.'
              : `OCR не завершён${updated.error_code ? ` (${updated.error_code})` : ''}. Проверьте частичный текст или введите его вручную.`,
          )
        } else timer = setTimeout(poll, 2000)
      } catch (cause) {
        if (cause.name !== 'AbortError') {
          setError(cause.message)
          timer = setTimeout(poll, 5000)
        }
      }
    }
    timer = setTimeout(poll, 1000)
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [task?.task_id, active])
  async function start() {
    if (lock.current || busy) return
    if (value && !window.confirm('Заменить текущий текст результатом нового OCR?')) return
    lock.current = true
    setSending(true)
    setError('')
    try {
      const media_ids = await photo.upload()
      const signature = JSON.stringify(media_ids)
      if (attempt.current?.signature !== signature || task)
        attempt.current = {
          signature,
          key: randomId(),
          body: {
            client_request_id: randomId(),
            purpose: 'ocr',
            input_mode: 'photo',
            media_ids,
            text: 'Распознавание текста OCR',
            privacy: { force_local: true, model_preference: 'local' },
          },
        }
      setTask(
        await api('/tasks', {
          method: 'POST',
          key: attempt.current.key,
          body: attempt.current.body,
        }),
      )
    } catch (cause) {
      if (cause.status >= 400 && cause.status < 500) attempt.current = null
      setError(cause.message)
    } finally {
      setSending(false)
      lock.current = false
    }
  }
  if (!photo.photos.length && !value && !task) return null
  return (
    <div className="page-stack">
      <Button
        variant="secondary"
        disabled={disabled || photo.preparing || !photo.photos.length || busy}
        onClick={start}
      >
        {busy ? 'Распознаём текст…' : 'Выполнить OCR'}
      </Button>
      <small>
        Извлечь полный текст документа или этикетки для поиска. Название и свойства вещи эта кнопка
        не заполняет. Обработка идёт на доверенном сервере, по одной фотографии. Проверьте
        результат: мелкий шрифт и нечёткие снимки могут распознаваться с ошибками.
      </small>
      {active && (
        <div className="toolbar">
          <StageRing task={task} />
          <Link to={`/tasks/${task.task_id}`}>Задача OCR</Link>
          <Button
            variant="text"
            onClick={async () => {
              try {
                setTask(await write(`/tasks/${task.task_id}/cancel`, {}))
              } catch (cause) {
                setError(cause.message)
              }
            }}
          >
            Остановить OCR
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {(value != null || task) && (
        <Input
          label="Полный текст OCR"
          as="textarea"
          rows={8}
          maxLength={100000}
          info="Полный распознанный текст хранится отдельно от краткого описания и используется текстовым поиском. Исправьте ошибки перед сохранением. Эта вещь и её текст будут доступны только локальным моделям."
          value={value || ''}
          disabled={disabled || busy}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </div>
  )
}
