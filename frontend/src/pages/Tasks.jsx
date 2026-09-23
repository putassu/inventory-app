import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { write } from '../api/client'
import { useTasks, terminalTask } from '../contexts/TaskContext'
import { useAuth } from '../contexts/AuthContext'
import { useResource } from '../hooks/useResource'
import { label } from '../utils/labels'
import { Button } from '../components/ui/Button'

function TaskCard({ task, detailed = false }) {
  const { user } = useAuth()
  const { addTask, refreshTasks } = useTasks()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const attempt = useRef(null)
  const current = task.progress?.current
  useEffect(() => {
    if (!current?.started_at || terminalTask(task.status) || task.status === 'waiting_for_review')
      return
    const received = Date.now()
    const initial = Math.max(
      0,
      new Date(task.timing?.server_time || received) - new Date(current.started_at),
    )
    const tick = () => setElapsed(Math.floor((initial + Date.now() - received) / 1000))
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [current?.started_at, task.status, task.timing?.server_time])
  async function action(name) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      if (attempt.current?.name !== name)
        attempt.current = {
          name,
          key: crypto.randomUUID(),
          body: name === 'cancel' ? {} : { client_request_id: crypto.randomUUID() },
        }
      const result = await write(
        `/tasks/${task.task_id}/${name}`,
        attempt.current.body,
        'POST',
        attempt.current.key,
      )
      if (result.task_id && result.status_version) addTask(result)
      await refreshTasks()
      attempt.current = null
    } catch (cause) {
      setError(cause.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <article className="card page-stack">
      <div className="toolbar">
        <h2>
          <Link to={`/tasks/${task.task_id}`}>
            {task.title || `Обработка: ${label(task.input_mode || 'text')}`}
          </Link>
        </h2>
        <span className={`status-badge status-${task.status}`}>{label(task.status)}</span>
      </div>
      <small>Создано: {new Date(task.created_at).toLocaleString('ru-RU')}</small>
      <p>
        Этап: {label(task.stage)}
        {!terminalTask(task.status) &&
          task.status !== 'waiting_for_review' &&
          current?.started_at && <span> · {elapsed} с</span>}
      </p>
      {task.progress?.percent != null ? (
        <progress max="100" value={task.progress.percent} aria-label="Прогресс обработки" />
      ) : (
        !terminalTask(task.status) &&
        task.status !== 'waiting_for_review' && (
          <p className="muted">Процент завершения пока неизвестен.</p>
        )
      )}
      {task.error_code && (
        <p className="error">
          Обработка остановлена: {task.error_code}. Можно повторить или продолжить вручную.
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="toolbar">
        {task.proposal_id && (
          <Link className="btn btn-primary" to={`/review/${task.proposal_id}`}>
            {task.status === 'waiting_for_review'
              ? 'Проверить и подтвердить'
              : 'Открыть предложение'}
          </Link>
        )}
        {task.result?.operation_id && (
          <Link to={`/operations/${task.result.operation_id}`}>Результат операции</Link>
        )}
        {task.status === 'succeeded' && !task.result?.operation_id && (
          <span>Обработка завершена. Результат ниже или в предложении.</span>
        )}
        {task.can_cancel && (
          <Button variant="secondary" disabled={busy} onClick={() => action('cancel')}>
            Отменить задачу
          </Button>
        )}
        {['failed', 'cancelled', 'expired'].includes(task.status) && (
          <>
            <Button disabled={busy} onClick={() => action('retry')}>
              Повторить обработку
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => action('manual-review')}>
              Продолжить вручную
            </Button>
          </>
        )}
        {user?.app_role === 'admin' && (
          <Link to={`/admin/tasks/${task.task_id}/trace`}>Диагностика</Link>
        )}
      </div>
      {detailed && (
        <>
          <h3>Стадии обработки</h3>
          <ol className="timeline">
            {task.progress?.history?.map((stage, index) => (
              <li key={index}>
                <strong>{label(stage.stage)}</strong> · {label(stage.status)}
                {stage.duration_ms != null &&
                  ` · ${(stage.duration_ms / 1000).toLocaleString('ru-RU')} с`}
                {stage.error_code && ` · ${stage.error_code}`}
              </li>
            ))}
          </ol>
          {task.result?.items?.map((item) => (
            <Link key={item.item_id || item.id} to={`/items/${item.item_id || item.id}`}>
              {item.name || 'Открыть вещь'}
            </Link>
          ))}
          {task.parent_task_id && <Link to={`/tasks/${task.parent_task_id}`}>Исходная задача</Link>}
        </>
      )}
    </article>
  )
}
export function Tasks() {
  const { activeTasks, refreshTasks, error } = useTasks()
  const [filter, setFilter] = useState('all')
  const [failure, setFailure] = useState('')
  const tests = {
    all: () => true,
    active: (task) => !terminalTask(task.status) && task.status !== 'waiting_for_review',
    review: (task) => task.status === 'waiting_for_review',
    done: (task) => terminalTask(task.status),
  }
  return (
    <section className="page-stack">
      <div className="toolbar">
        <h1>Задачи</h1>
        <Link className="btn btn-primary" to="/capture">
          Новая задача
        </Link>
        <Button
          variant="secondary"
          onClick={() => refreshTasks().catch((cause) => setFailure(cause.message))}
        >
          Обновить
        </Button>
      </div>
      {(error || failure) && (
        <p role="alert" className="error">
          {error || failure}
        </p>
      )}
      <div className="toolbar" aria-label="Фильтр задач">
        {Object.entries({
          all: 'Все',
          active: 'Активные',
          review: 'На проверке',
          done: 'Завершённые',
        }).map(([value, text]) => (
          <Button
            key={value}
            variant={value === filter ? 'primary' : 'secondary'}
            aria-pressed={value === filter}
            onClick={() => setFilter(value)}
          >
            {text} ({activeTasks.filter(tests[value]).length})
          </Button>
        ))}
      </div>
      {activeTasks
        .filter(tests[filter])
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map((task) => (
          <TaskCard key={task.task_id} task={task} />
        ))}
      {!activeTasks.some(tests[filter]) && <p>В этой категории пока нет задач.</p>}
    </section>
  )
}
export function TaskDetail() {
  const { id } = useParams()
  const { activeTasks, addTask } = useTasks()
  const { data, error, loading } = useResource(`/tasks/${id}`)
  useEffect(() => {
    if (data) addTask(data)
  }, [data, addTask])
  const task = activeTasks.find((task) => task.task_id === id) || data
  return (
    <section className="page-stack">
      <Link to="/tasks">← Задачи</Link>
      {error && <p role="alert">{error.message}</p>}
      {loading && !task && <p>Загрузка…</p>}
      {task && <TaskCard task={task} detailed />}
    </section>
  )
}
export function BatchDetail() {
  const { id } = useParams()
  const { activeTasks } = useTasks()
  const { data, error, reload } = useResource(`/ingestion-batches/${id}`)
  useEffect(() => {
    const timer = setInterval(reload, 5000)
    return () => clearInterval(timer)
  }, [reload])
  return (
    <section className="page-stack">
      <h1>{data?.name || 'Группа загрузки'}</h1>
      {error && <p role="alert">{error.message}</p>}
      {Object.entries(data?.counts || {}).map(([status, count]) => (
        <p key={status}>
          {label(status)}: {count}
        </p>
      ))}
      {activeTasks
        .filter((task) => task.batch_id === id)
        .map((task) => (
          <TaskCard key={task.task_id} task={task} />
        ))}
    </section>
  )
}
