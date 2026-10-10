import { useState } from 'react'
import { useResource } from '../../hooks/useResource'
import { write } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { Help } from '../../components/ui/Help'
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
          <h3 className="field-label">
            {model.logical_name}
            <Help title={`Модель ${model.logical_name}`}>
              Логическое развёртывание связывает стадию обработки с фактической моделью. local_vlm —
              извлечение полей; privacy_asr — проверка приватности; local_audio — голос;
              cloud_primary — внешний маршрут; embedding — поисковые векторы. Имя модели само по
              себе не определяет доверие: его задаёт trust_domain.
            </Help>
          </h3>
          <p>
            {model.actual_model_id} · {model.trust_domain}
            <Help title="Модель и доверенный контур">
              actual_model_id — имя в API inference-сервера. trust_domain=local обозначает
              доверенный сервер владельца, даже если он доступен по сети; cloud — внешний сервис.
              Чувствительные материалы не отправляются во внешний контур независимо от предпочтения
              облака.
            </Help>
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
            <Help title="Проверить подключение">
              Отправляет синтетический запрос модели, поэтому занимает inference и может выполняться
              долго. Это не простой HTTP ping. Не запускайте параллельно с другой обработкой на
              однопоточном сервере. Успешная проверка нужна для включения развёртывания.
            </Help>
            <Button
              disabled={busy || (!model.enabled && !model.capabilities?.verified_connection)}
              onClick={() => run(model, { enabled: !model.enabled })}
            >
              {model.enabled ? 'Выключить' : 'Включить'}
            </Button>
            <Help title="Включение модели">
              Разрешает выбирать это развёртывание для новых вызовов. Не отменяет правила
              приватности, лимиты и обслуживание. Выключение не гарантирует остановку уже
              отправленного запроса на inference-сервере.
            </Help>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => run(model, { maintenance: !model.maintenance })}
            >
              {model.maintenance ? 'Завершить обслуживание' : 'Обслуживание'}
            </Button>
            <Help title="Обслуживание модели">
              Временно исключает модель из новых вызовов, сохраняя её регистрацию. Используйте при
              перезапуске или замене inference-сервиса. Уже выполняющийся физический запрос
              требуется дождаться или остановить на сервере.
            </Help>
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
