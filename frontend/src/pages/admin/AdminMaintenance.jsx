import { useState } from 'react'
import { useResource } from '../../hooks/useResource'
import { usePaged } from '../../hooks/usePaged'
import { useJob } from '../../hooks/useJob'
import { useMutation } from '../../hooks/useMutation'
import { Button } from '../../components/ui/Button'
import { label } from '../../utils/labels'
export function AdminMaintenance() {
  const health = useResource('/admin/health'),
    metrics = useResource('/admin/metrics'),
    audit = usePaged('/admin/audit?limit=20')
  const [jobId, setJobId] = useState(null),
    [preview, setPreview] = useState(null),
    [confirm, setConfirm] = useState(false),
    [result, setResult] = useState(null)
  const job = useJob(jobId ? `/admin/jobs/${jobId}` : null),
    mutation = useMutation()
  return (
    <div className="stack">
      <h2>Обслуживание</h2>
      {[health.error, metrics.error, audit.error, job.error].filter(Boolean).map((e, i) => (
        <p role="alert" key={i}>
          {e.message}
        </p>
      ))}
      {mutation.error && <p role="alert">{mutation.error}</p>}
      <section className="card">
        <h3>Сервисы</h3>
        {Object.entries(health.data || {}).map(([name, value]) => (
          <p key={name}>
            {name}:{' '}
            {typeof value === 'boolean'
              ? value
                ? 'Доступен'
                : 'Недоступен'
              : JSON.stringify(value)}
          </p>
        ))}
        <Button
          variant="secondary"
          onClick={() => {
            health.reload()
            metrics.reload()
          }}
        >
          Обновить
        </Button>
      </section>
      <details className="card">
        <summary>Метрики</summary>
        <pre>{JSON.stringify(metrics.data, null, 2)}</pre>
      </details>
      <section className="card stack">
        <h3>Поисковый индекс</h3>
        <Button
          disabled={mutation.busy || (jobId && !['succeeded', 'failed'].includes(job.data?.status))}
          onClick={async () => {
            const next = await mutation.run('/admin/search/reindex')
            if (next) setJobId(next.job_id)
          }}
        >
          Переиндексировать текущий инвентарь
        </Button>
        {job.data && <p role="status">{label(job.data.status)}</p>}
      </section>
      <section className="card stack">
        <h3>Очистка по срокам хранения</h3>
        <p>
          Запускается серверная очистка всех рабочих областей: непривязанные файлы, истёкшие
          экспорты, черновики и другие данные согласно действующим срокам хранения. Предпросмотр
          ниже показывает только непривязанные файлы.
        </p>
        <Button
          variant="secondary"
          disabled={mutation.busy}
          onClick={async () => {
            setConfirm(false)
            setPreview(await mutation.run('/admin/gc/preview'))
          }}
        >
          Оценить непривязанные файлы
        </Button>
        {preview && (
          <>
            <p>
              Файлов: {preview.count}, байт: {preview.bytes}
            </p>
            <label>
              <input
                type="checkbox"
                checked={confirm}
                onChange={(e) => setConfirm(e.target.checked)}
              />{' '}
              Подтверждаю полную серверную очистку по действующим срокам хранения
            </label>
            <Button
              variant="danger"
              disabled={!confirm || mutation.busy}
              onClick={async () => {
                const next = await mutation.run('/admin/gc/run')
                if (next) {
                  setResult(next)
                  setPreview(null)
                  setConfirm(false)
                  audit.reload()
                }
              }}
            >
              Запустить очистку
            </Button>
          </>
        )}
        {result && <pre>{JSON.stringify(result, null, 2)}</pre>}
      </section>
      <section className="stack">
        <h3>Журнал действий администратора</h3>
        {audit.items.map((row) => (
          <details className="card" key={row.id}>
            <summary>
              {row.action} · {new Date(row.created_at).toLocaleString()}
            </summary>
            <pre>{JSON.stringify(row.details, null, 2)}</pre>
          </details>
        ))}
        {audit.next_cursor && (
          <Button disabled={audit.loading} onClick={audit.more}>
            Ещё
          </Button>
        )}
      </section>
    </div>
  )
}
