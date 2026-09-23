import { useState } from 'react'
import { api } from '../api/client'
import { usePaged } from '../hooks/usePaged'
import { useJob } from '../hooks/useJob'
import { useMutation } from '../hooks/useMutation'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { label } from '../utils/labels'
export function DataPage() {
  const [format, setFormat] = useState('json'),
    [media, setMedia] = useState(false),
    [history, setHistory] = useState(false)
  const [exportId, setExportId] = useState(null),
    [downloadError, setDownloadError] = useState('')
  const [ids, setIds] = useState(''),
    [preview, setPreview] = useState(null),
    [confirmed, setConfirmed] = useState(false)
  const mutation = useMutation(),
    jobs = usePaged('/purge-jobs?limit=20')
  const exported = useJob(exportId ? `/exports/${exportId}` : null)
  async function start() {
    const result = await mutation.run('/exports', {
      format,
      include_media: media,
      include_history: history,
    })
    if (result) setExportId(result.export_id)
  }
  async function download() {
    setDownloadError('')
    try {
      const blob = await api(`/exports/${exportId}/download`, { blob: true })
      const url = URL.createObjectURL(blob),
        link = document.createElement('a')
      link.href = url
      link.download = `inventory-${exportId}.${blob.type === 'application/zip' ? 'zip' : 'json'}`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      setDownloadError(e.message)
    }
  }
  async function previewDeletion() {
    setPreview(null)
    setConfirmed(false)
    const result = await mutation.run('/deletion-previews', {
      item_ids: [...new Set(ids.split(/[,\s]+/).filter(Boolean))],
    })
    if (result) setPreview(result)
  }
  async function purge() {
    const result = await mutation.run('/purge-jobs', {
      preview_id: preview.preview_id,
      preview_revision: preview.preview_revision,
      preview_hash: preview.preview_hash,
      explicit_confirmation: confirmed,
    })
    if (result) {
      setPreview(null)
      setConfirmed(false)
      setIds('')
      jobs.reload()
    }
  }
  return (
    <div className="stack">
      <h1>Данные</h1>
      {(mutation.error || downloadError) && <p role="alert">{mutation.error || downloadError}</p>}
      <section className="card stack">
        <h2>Экспорт</h2>
        <Select label="Формат" value={format} onChange={(e) => setFormat(e.target.value)}>
          <option value="json">JSON</option>
          <option value="csv">CSV (ZIP)</option>
          <option value="zip">ZIP</option>
        </Select>
        <label>
          <input type="checkbox" checked={media} onChange={(e) => setMedia(e.target.checked)} />{' '}
          Включить медиа
        </label>
        <label>
          <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} />{' '}
          Включить историю
        </label>
        <Button
          disabled={
            mutation.busy ||
            (exportId &&
              !['succeeded', 'failed', 'expired', 'revoked'].includes(exported.data?.status))
          }
          onClick={start}
        >
          Создать экспорт
        </Button>
        {exported.error && (
          <p role="alert">
            {exported.error.message}
            <Button onClick={exported.reload}>Проверить снова</Button>
          </p>
        )}
        {exported.data && (
          <p role="status">
            {label(exported.data.status)} · Срок доступа:{' '}
            {new Date(exported.data.expires_at).toLocaleString()}
          </p>
        )}
        {exported.data?.download && <Button onClick={download}>Скачать файл</Button>}
      </section>
      <section className="card stack">
        <h2>Безвозвратное удаление</h2>
        <p>
          Сначала архивируйте вещи в каталоге. Предпросмотр покажет связанные данные, которые будут
          удалены.
        </p>
        <Input
          label="Идентификаторы вещей через запятую"
          value={ids}
          onChange={(e) => {
            setIds(e.target.value)
            setPreview(null)
            setConfirmed(false)
          }}
        />
        <Button
          variant="secondary"
          disabled={mutation.busy || !ids.trim()}
          onClick={previewDeletion}
        >
          Показать последствия
        </Button>
        {preview && (
          <div className="stack notice">
            <h3>Последствия удаления</h3>
            <pre>{JSON.stringify(preview.impact, null, 2)}</pre>
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />{' '}
              Я проверил перечень и подтверждаю безвозвратное удаление после периода отмены
            </label>
            <Button variant="danger" disabled={mutation.busy || !confirmed} onClick={purge}>
              Назначить удаление
            </Button>
          </div>
        )}
        <h3>Задания удаления</h3>
        <Button variant="secondary" onClick={jobs.reload}>
          Обновить
        </Button>
        {jobs.error && <p role="alert">{jobs.error.message}</p>}
        {jobs.items.map((job) => (
          <div className="card" key={job.purge_job_id}>
            <p>
              {label(job.status)} · Не раньше {new Date(job.not_before).toLocaleString()}
            </p>
            {['scheduled', 'pending', 'grace_period', 'queued'].includes(job.status) && (
              <Button
                disabled={mutation.busy}
                onClick={async () => {
                  if (
                    await mutation.run(`/purge-jobs/${job.purge_job_id}/cancel`, {
                      expected_version: job.version,
                      explicit_confirmation: true,
                    })
                  )
                    jobs.reload()
                }}
              >
                Отменить удаление
              </Button>
            )}
          </div>
        ))}
        {jobs.next_cursor && (
          <Button disabled={jobs.loading} onClick={jobs.more}>
            Ещё
          </Button>
        )}
      </section>
    </div>
  )
}
