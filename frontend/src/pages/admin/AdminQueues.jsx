import { useEffect, useState } from 'react'
import { useResource } from '../../hooks/useResource'
import { write } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { label } from '../../utils/labels'
export function AdminQueues() {
  const { data, error: loadError, reload } = useResource('/admin/queues')
  const [stopped, setStopped] = useState(false),
    [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  useEffect(() => {
    const timer = setInterval(reload, 10000)
    return () => clearInterval(timer)
  }, [reload])
  async function run(path, body = {}) {
    setBusy(true)
    setError('')
    try {
      await write(path, body)
      setStopped(false)
      reload()
    } catch (e) {
      setError(e.message)
      if (e.status === 409) reload()
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="stack">
      <h2>Очереди и GPU</h2>
      {(error || loadError) && <p role="alert">{error || loadError.message}</p>}
      {!data && !loadError && <p>Загрузка…</p>}
      {data && (
        <>
          {['default', 'bulk', 'cpu', 'cloud', 'maintenance'].map((name) => (
            <div className="card actions" key={name}>
              <div>
                <h3>{name}</h3>
                {data.queues
                  .filter((q) => q.name === name)
                  .map((q) => (
                    <span key={q.status}>
                      {label(q.status)}: {q.count}{' '}
                    </span>
                  ))}
              </div>
              <Button
                disabled={busy}
                variant="secondary"
                onClick={() =>
                  run(
                    `/admin/queues/${name}/${data.controls?.[`queue:${name}`]?.paused ? 'resume' : 'pause'}`,
                  )
                }
              >
                {data.controls?.[`queue:${name}`]?.paused ? 'Возобновить' : 'Приостановить'}
              </Button>
            </div>
          ))}
          <section className="card stack">
            <h3>GPU: {data.gpu?.state || 'нет данных'}</h3>
            {data.gpu?.state === 'quarantined' && (
              <>
                <p>
                  Сначала физически остановите зависший инференс. Снятие карантина разрешит запуск
                  следующей задачи.
                </p>
                <Input
                  label="Причина восстановления"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <label>
                  <input
                    type="checkbox"
                    checked={stopped}
                    onChange={(e) => setStopped(e.target.checked)}
                  />{' '}
                  Я проверил, что процесс инференса остановлен
                </label>
                <Button
                  variant="danger"
                  disabled={busy || !stopped || !reason.trim()}
                  onClick={() =>
                    run('/admin/gpu/recover', {
                      expected_fencing_token: data.gpu.fencing_token,
                      physical_inference_stopped: stopped,
                      reason,
                    })
                  }
                >
                  Снять карантин
                </Button>
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}
