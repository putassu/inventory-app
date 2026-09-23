import { useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useResource } from '../../hooks/useResource'
import { write } from '../../api/client'
import { label } from '../../utils/labels'
import { Button } from '../../components/ui/Button'
export function TaskTrace() {
  const { id } = useParams(),
    navigate = useNavigate()
  const { data, error: loadError } = useResource(`/admin/tasks/${id}/trace`)
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  async function replay() {
    setBusy(true)
    setError('')
    try {
      const task = await write(`/admin/tasks/${id}/replay`, {})
      navigate(`/tasks/${task.task_id}`)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="stack">
      <Link to={`/tasks/${id}`}>К задаче</Link>
      <h2>Диагностика задачи</h2>
      {(error || loadError) && <p role="alert">{error || loadError.message}</p>}
      {data && (
        <>
          <p>
            {label(data.status)} · {label(data.stage)} ·{' '}
            {data.progress?.percent == null
              ? 'Точный процент неизвестен'
              : `${data.progress.percent}%`}
          </p>
          <p>
            Диагностический повтор создаёт отдельную задачу без автоматического изменения учёта.
          </p>
          <Button disabled={busy} onClick={replay}>
            Повторить для диагностики
          </Button>
          <details>
            <summary>Прогресс по стадиям</summary>
            <pre>{JSON.stringify(data.progress, null, 2)}</pre>
          </details>
          <h3>Попытки</h3>
          {data.attempts.map((attempt, i) => (
            <details className="card" key={attempt.id || i}>
              <summary>
                Попытка {i + 1} · {attempt.status || attempt.stage}
              </summary>
              <pre>{JSON.stringify(attempt, null, 2)}</pre>
            </details>
          ))}
        </>
      )}
    </div>
  )
}
