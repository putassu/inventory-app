import { useState } from 'react'
import { useResource } from '../../hooks/useResource'
import { write } from '../../api/client'
import { Button } from '../../components/ui/Button'
export function AdminModels() {
  const { data, error: loadError, reload } = useResource('/admin/models')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function run(model, changes) {
    setBusy(true)
    setError('')
    try {
      await write(
        `/admin/models/${model.id}${changes ? '' : '/health-check'}`,
        changes ? { expected_version: model.version, ...changes } : {},
        changes ? 'PATCH' : 'POST',
      )
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
      <h2>Модели</h2>
      {(error || loadError) && <p role="alert">{error || loadError.message}</p>}
      {!data && !loadError && <p>Загрузка…</p>}
      {data?.items.map((model) => (
        <section className="card stack" key={model.id}>
          <h3>{model.logical_name}</h3>
          <p>
            {model.actual_model_id} · {model.trust_domain}
          </p>
          <p>
            {model.enabled ? 'Включена' : 'Выключена'}
            {model.maintenance && ' · Обслуживание'}
          </p>
          <p>
            Проверена: {model.checked_at ? new Date(model.checked_at).toLocaleString() : 'ещё нет'}
          </p>
          <div className="actions">
            <Button disabled={busy} onClick={() => run(model)}>
              Проверить подключение
            </Button>
            <Button
              disabled={busy || (!model.enabled && !model.capabilities?.verified_connection)}
              onClick={() => run(model, { enabled: !model.enabled })}
            >
              {model.enabled ? 'Выключить' : 'Включить'}
            </Button>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => run(model, { maintenance: !model.maintenance })}
            >
              {model.maintenance ? 'Завершить обслуживание' : 'Обслуживание'}
            </Button>
          </div>
          <details>
            <summary>Возможности модели</summary>
            <pre>{JSON.stringify(model.capabilities, null, 2)}</pre>
          </details>
        </section>
      ))}
    </div>
  )
}
