import { useCallback, useEffect, useRef, useState } from 'react'
import { api, write } from './api'

const queueNames = {
  default: 'Обычная',
  bulk: 'Массовая',
  cpu: 'Подготовка',
  cloud: 'Внешние модели',
  maintenance: 'Обслуживание',
}
const states = {
  accepted: 'Принято',
  preparing: 'Подготовка',
  retry_wait: 'Ожидает повтора',
  waiting_for_review: 'Ожидает проверки',
  applying: 'Сохраняется',
  cancelled: 'Отменено',
  expired: 'Срок проверки истёк',
  pending: 'Ожидает обработки',
  processed: 'Обработано',
  published: 'Передано',
  dead: 'Требует внимания',
  idle: 'Свободен',
  busy: 'Занят',
  quarantined: 'Требует восстановления',
  queued: 'В очереди',
  succeeded: 'Готово',
  failed: 'Ошибка',
  running: 'Выполняется',
}

const loadData = () =>
  Promise.all([
    api('/admin/models'),
    api('/admin/queues'),
    api('/admin/metrics'),
    api('/admin/audit'),
  ])

export default function AdminTools() {
  const [models, setModels] = useState([])
  const [queues, setQueues] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [audit, setAudit] = useState({ items: [] })
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [stopped, setStopped] = useState(false)
  const [reason, setReason] = useState('')
  const [gcPreview, setGcPreview] = useState(null)
  const [job, setJob] = useState(null)
  const lastFence = useRef(null)
  const update = useCallback(([m, q, counts, log]) => {
    if (lastFence.current !== q.gpu?.fencing_token) {
      lastFence.current = q.gpu?.fencing_token
      setStopped(false)
      setReason('')
    }
    setModels(m.items)
    setQueues(q)
    setMetrics(counts)
    setAudit(log)
  }, [])
  useEffect(() => {
    loadData()
      .then(update)
      .catch((e) => setError(e.message))
  }, [update])
  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return
    const timer = setTimeout(
      () =>
        api('/admin/jobs/' + job.job_id)
          .then(setJob)
          .catch((e) => setError(e.message)),
      2000,
    )
    return () => clearTimeout(timer)
  }, [job])
  async function run(action) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
      update(await loadData())
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-label="Администрирование сервисов">
      <div className="heading">
        <h2>Сервисы и очереди</h2>
        <button className="secondary" disabled={busy} onClick={() => run(async () => {})}>
          Обновить состояние
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      <section className="panel">
        <h3>Модели</h3>
        <p className="muted">
          Проверка отправляет синтетический запрос. Для включения модели нужна успешная проверка
          соединения.
        </p>
        {models.map((model) => (
          <article className="card" key={model.id} aria-label={'Модель ' + model.logical_name}>
            <div className="row">
              <div>
                <strong>{model.logical_name}</strong>
                <small>
                  {model.actual_model_id} ·{' '}
                  {model.trust_domain === 'local' ? 'Доверенный сервер' : 'Внешняя модель'}
                </small>
              </div>
              <span>
                {model.maintenance ? 'Обслуживание' : model.enabled ? 'Включена' : 'Выключена'}
              </span>
            </div>
            <p className="muted">
              {model.checked_at
                ? `Проверена ${new Date(model.checked_at).toLocaleString('ru')}`
                : 'Ещё не проверена'}
              {model.capabilities?.supports_audio ? ' · Аудио' : ''}
            </p>
            <div className="actions">
              <button
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await write(`/admin/models/${model.id}/health-check`, {})
                    setNotice('Соединение с моделью проверено.')
                  })
                }
              >
                Проверить модель
              </button>
              <button
                className="secondary"
                disabled={
                  busy ||
                  (!model.enabled && !(model.checked_at && model.capabilities?.verified_connection))
                }
                onClick={() =>
                  run(() =>
                    write(
                      '/admin/models/' + model.id,
                      { expected_version: model.version, enabled: !model.enabled },
                      'PATCH',
                    ),
                  )
                }
              >
                {model.enabled ? 'Выключить' : 'Включить'}
              </button>
              <button
                className="quiet"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    write(
                      '/admin/models/' + model.id,
                      { expected_version: model.version, maintenance: !model.maintenance },
                      'PATCH',
                    ),
                  )
                }
              >
                {model.maintenance ? 'Завершить обслуживание' : 'На обслуживание'}
              </button>
            </div>
          </article>
        ))}
      </section>
      <section className="panel">
        <h3>Очереди</h3>
        {Object.entries(queueNames).map(([name, label]) => {
          const paused = queues?.controls?.['queue:' + name]?.paused
          return (
            <div className="row queue-row" key={name}>
              <div>
                <strong>{label}</strong>
                <small>
                  {paused ? 'Приостановлена' : 'Работает'} · Задач:{' '}
                  {(queues?.queues || [])
                    .filter((q) => q.name === name)
                    .reduce((sum, q) => sum + q.count, 0)}
                </small>
              </div>
              <button
                className="secondary"
                disabled={busy || !queues}
                onClick={() =>
                  run(() => write(`/admin/queues/${name}/${paused ? 'resume' : 'pause'}`, {}))
                }
              >
                {paused ? 'Продолжить' : 'Приостановить'}: {label}
              </button>
            </div>
          )
        })}
        <h3>GPU</h3>
        <p>{states[queues?.gpu?.state] || queues?.gpu?.state || 'Нет данных'}</p>
        {queues?.gpu?.state === 'quarantined' && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              run(async () => {
                await write('/admin/gpu/recover', {
                  expected_fencing_token: queues.gpu.fencing_token,
                  physical_inference_stopped: stopped,
                  reason,
                })
                setStopped(false)
                setReason('')
                setNotice('GPU снова доступен для обработки.')
              })
            }}
          >
            <p className="notice">
              Сначала остановите зависший inference в обслуживающем сервисе. Снятие блокировки
              разрешает новый вызов модели.
            </p>
            <label>
              Причина восстановления
              <input
                required
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={stopped}
                onChange={(e) => setStopped(e.target.checked)}
              />
              Подтверждаю: физическое выполнение inference остановлено
            </label>
            <button disabled={busy || !stopped || !reason.trim()}>Восстановить GPU</button>
          </form>
        )}
      </section>
      <section className="panel">
        <h3>Обслуживание</h3>
        <div className="actions">
          <button
            disabled={busy || (job && ['queued', 'running'].includes(job.status))}
            onClick={() => run(async () => setJob(await write('/admin/search/reindex', {})))}
          >
            Перестроить поиск
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => run(async () => setGcPreview(await write('/admin/gc/preview', {})))}
          >
            Предпросмотр очистки
          </button>
        </div>
        {job && <p role="status">Перестроение: {states[job.status] || job.status}</p>}
        {gcPreview && (
          <div className="notice">
            <p>{gcPreview.policy}</p>
            <p>
              Непривязанных файлов: {gcPreview.count}; объём: {gcPreview.bytes} байт. Применятся
              также действующие сроки хранения задач, черновиков и экспорта.
            </p>
            <button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const result = await write('/admin/gc/run', {})
                  setGcPreview(null)
                  setNotice(
                    result.status === 'completed'
                      ? 'Очистка по действующей политике завершена.'
                      : 'Очистка выполняется. Обновите состояние позже.',
                  )
                })
              }
            >
              Запустить очистку
            </button>
          </div>
        )}
      </section>
      <section className="panel">
        <h3>Метрики</h3>
        {metrics && (
          <>
            <p>
              Попыток распознавания: {metrics.attempts}. Карточек, ожидающих индекс:{' '}
              {metrics.index_lag}.
            </p>
            <div className="form-grid">
              <div>
                <strong>Задачи</strong>
                {Object.entries(metrics.tasks || {}).map(([name, count]) => (
                  <p key={name}>
                    {states[name] || name}: {count}
                  </p>
                ))}
              </div>
              <div>
                <strong>Фоновые события</strong>
                {Object.entries(metrics.outbox || {}).map(([name, count]) => (
                  <p key={name}>
                    {states[name] || name}: {count}
                  </p>
                ))}
              </div>
            </div>
            {metrics.oldest_pending && (
              <p>
                Самая ранняя задача в очереди:{' '}
                {new Date(metrics.oldest_pending).toLocaleString('ru')}
              </p>
            )}
          </>
        )}
      </section>
      <section className="panel">
        <h3>Журнал администратора</h3>
        {audit.items.map((row) => (
          <article className="queue-row" key={row.id}>
            <strong>{row.action}</strong>
            <small>
              {new Date(row.created_at).toLocaleString('ru')} · {row.actor_id || 'Система'}
            </small>
            {row.reason && <p>{row.reason}</p>}
            <details>
              <summary>Подробности</summary>
              <pre>{JSON.stringify(row.details, null, 2)}</pre>
            </details>
          </article>
        ))}
        {audit.next_cursor && (
          <button
            className="secondary"
            disabled={busy}
            onClick={async () => {
              try {
                const more = await api(
                  '/admin/audit?cursor=' + encodeURIComponent(audit.next_cursor),
                )
                setAudit((old) => ({ ...more, items: [...old.items, ...more.items] }))
              } catch (e) {
                setError(e.message)
              }
            }}
          >
            Следующие записи
          </button>
        )}
      </section>
    </section>
  )
}
