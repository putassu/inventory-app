import { useEffect, useState } from 'react'
import { useResource } from '../../hooks/useResource'
import { write } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { label } from '../../utils/labels'
import { Help } from '../../components/ui/Help'
const queueHelp = {
  default: 'Обычные задачи распознавания, добавленные пользователем.',
  bulk: 'Задачи массового ввода. Делят доступное время модели с обычной очередью согласно весам.',
  cpu: 'Подготовка файлов и применение подтверждённых команд. Пауза может задержать сохранение ручных вещей и мест; LLM для этих операций не нужна.',
  cloud: 'Вызовы внешних моделей для материалов, которым разрешена внешняя обработка.',
  maintenance:
    'Фоновые работы обслуживания, включая обновление поискового индекса и эмбеддингов. На слабом inference они тоже потребляют ресурсы модели.',
}
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
                <h3 className="field-label">
                  {name}
                  <Help title={`Очередь ${name}`}>
                    {queueHelp[name]} Пауза запрещает новую отправку из этой очереди; уже начатые
                    работы продолжаются. Возобновление разрешает разбор ожидающих задач, поэтому
                    сначала проверьте их число. PostgreSQL хранит задания, Redis используется для
                    доставки.
                  </Help>
                </h3>
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
            <h3 className="field-label">
              GPU: {data.gpu?.state || 'нет данных'}
              <Help title="Состояние GPU">
                Общая блокировка inference приложения: idle — свободно, running — вызов выполняется,
                quarantined — исход предыдущего вызова неизвестен. Карантин не доказывает поломку
                модели. Истечение lease и отмена задачи не доказывают физическую остановку
                вычисления. Fencing token защищает от поздних ответов старого worker.
              </Help>
            </h3>
            {data.gpu?.state === 'quarantined' && (
              <>
                <p>
                  Сначала физически остановите зависший инференс. Снятие карантина разрешит запуск
                  следующей задачи.
                </p>
                <Input
                  label="Причина восстановления"
                  info="Пояснение попадёт в аудит вместе с новым fencing token. Укажите, как проверили завершение прежнего запроса. Восстановление разрешает следующий вызов; оно не останавливает старое вычисление."
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
                  <Help title="Подтверждение остановки inference">
                    Проверьте завершение или остановку прежнего физического запроса на
                    inference-сервере. Ответ сервера на ping и отсутствие задачи в интерфейсе
                    недостаточны. Это подтверждение позволяет безопасно открыть слот для следующего
                    единственного вызова.
                  </Help>
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
