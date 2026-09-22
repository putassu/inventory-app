import { useEffect, useState } from 'react'
import { api, write } from './api'
import AdminTools from './AdminTools'
import Reminders from './Reminders'

export default function Settings({ admin, onChanged }) {
  const [page, setPage] = useState('preferences')
  return (
    <>
      <nav className="subnav" aria-label="Управление настройками">
        <button
          className={page === 'preferences' ? 'active' : ''}
          onClick={() => setPage('preferences')}
        >
          Параметры
        </button>
        <button
          className={page === 'reminders' ? 'active' : ''}
          onClick={() => setPage('reminders')}
        >
          Напоминания о сроках
        </button>
        {admin && (
          <button
            className={page === 'services' ? 'active' : ''}
            onClick={() => setPage('services')}
          >
            Сервисы и очереди
          </button>
        )}
      </nav>
      {page === 'preferences' && <Preferences admin={admin} onChanged={onChanged} />}
      {page === 'reminders' && <Reminders />}
      {page === 'services' && admin && <AdminTools />}
    </>
  )
}

function Preferences({ admin, onChanged }) {
  const [section, setSection] = useState('personal')
  const [schema, setSchema] = useState([])
  const [current, setCurrent] = useState(null)
  const [changes, setChanges] = useState({})
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [diagnostics, setDiagnostics] = useState(null)
  const [busy, setBusy] = useState(false)
  const [history, setHistory] = useState([])
  const [targetRevision, setTargetRevision] = useState('')
  const [rollbackReason, setRollbackReason] = useState('')
  const prefix = section === 'admin' ? '/admin/settings' : '/settings'
  useEffect(() => {
    let active = true
    Promise.all([api(prefix + '/schema'), api(prefix)])
      .then(([definition, values]) => {
        if (active) {
          setSchema(definition.fields)
          setCurrent(values)
          setChanges({})
          setPreview(null)
          setError('')
        }
      })
      .catch((e) => active && setError(e.message))
    return () => {
      active = false
    }
  }, [prefix])
  const values = current?.desired || current?.values || {}
  const body = {
    expected_revision: current?.desired_revision,
    changes: Object.entries(changes).map(([key, value]) => ({ key, value })),
    reason,
  }
  async function save() {
    setBusy(true)
    try {
      setError('')
      if (section === 'admin' && !preview) {
        setPreview(await write(prefix + '/validate', body))
        return
      }
      const result = await write(
        prefix,
        section === 'admin'
          ? { ...body, impact_confirmed: !!preview }
          : { expected_version: current.version, changes: body.changes },
        'PATCH',
      )
      setCurrent(result)
      setChanges({})
      setPreview(null)
      onChanged?.()
    } catch (e) {
      setError(e.message)
      if (e.code === 'VERSION_CONFLICT') {
        setCurrent(e.details?.current || (await api(prefix)))
        setPreview(null)
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="panel">
      <div className="heading">
        <h2>Настройки</h2>
        {admin && (
          <select
            aria-label="Раздел настроек"
            value={section}
            onChange={(e) => setSection(e.target.value)}
          >
            <option value="personal">Личные</option>
            <option value="admin">Администратора</option>
          </select>
        )}
      </div>
      {current?.status === 'pending_restart' && (
        <p className="notice">
          Ожидается перезапуск: {current.components_pending.join(', ')}. Действует ревизия{' '}
          {current.effective_revision}.
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="settings-list">
        {schema.map((field) => {
          const value = field.key in changes ? changes[field.key] : values[field.key]
          const change = (value) => {
            setChanges((old) => ({ ...old, [field.key]: value }))
            setPreview(null)
          }
          return (
            <label key={field.key}>
              <span>
                {field.description_ru}
                {field.editable === false && (
                  <small>{field.disabled_reason || 'Параметр недоступен для изменения'}</small>
                )}
                <small>
                  {field.apply_mode === 'requires_restart'
                    ? 'После перезапуска'
                    : field.apply_mode === 'immediate'
                      ? 'Сразу'
                      : 'Для новых задач'}
                </small>
              </span>
              {field.type === 'bool' ? (
                <input
                  type="checkbox"
                  disabled={field.editable === false || busy}
                  checked={!!value}
                  onChange={(e) => change(e.target.checked)}
                />
              ) : field.enum?.length ? (
                <select
                  disabled={field.editable === false || busy}
                  value={value ?? ''}
                  onChange={(e) => change(e.target.value || null)}
                >
                  {field.nullable && <option value="">Не задано</option>}
                  {field.enum.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              ) : field.type === 'list' ? (
                <input
                  disabled={field.editable === false || busy}
                  value={(value || []).join(', ')}
                  onChange={(e) =>
                    change(
                      e.target.value
                        .split(',')
                        .map((v) => v.trim())
                        .filter(Boolean),
                    )
                  }
                />
              ) : (
                <input
                  disabled={field.editable === false || busy}
                  type={['int', 'float', 'decimal'].includes(field.type) ? 'number' : 'text'}
                  step={field.type === 'int' ? 1 : 'any'}
                  min={field.min ?? undefined}
                  max={field.max ?? undefined}
                  value={value ?? ''}
                  onChange={(e) =>
                    change(
                      e.target.value === '' && field.nullable
                        ? null
                        : ['int', 'float'].includes(field.type)
                          ? Number(e.target.value)
                          : e.target.value,
                    )
                  }
                />
              )}
            </label>
          )
        })}
      </div>
      {section === 'admin' && (
        <label>
          Причина изменения
          <input
            value={reason}
            onChange={(e) => {
              setReason(e.target.value)
              setPreview(null)
            }}
          />
        </label>
      )}
      {preview && (
        <div className="notice">
          <p>
            Изменено параметров: {preview.changes.length}.{' '}
            {preview.components_pending.length
              ? 'Потребуется перезапуск воркеров.'
              : 'Перезапуск не требуется.'}
          </p>
          {preview.retention_reduced.length > 0 && (
            <>
              <p>Сокращается срок хранения: {preview.retention_reduced.join(', ')}.</p>
              <p>
                {preview.impact?.policy || 'Дополнительные объекты для очистки:'} Карточек:{' '}
                {preview.impact?.archived_items ?? 0}; материалов задач:{' '}
                {preview.impact?.task_inputs ?? 0}; черновиков: {preview.impact?.review_drafts ?? 0}
                ; файлов: {preview.impact?.media_count ?? 0} ({preview.impact?.media_bytes ?? 0}{' '}
                байт).
              </p>
              {preview.impact?.next_cleanup_at && (
                <p>
                  Ближайшая очистка: {new Date(preview.impact.next_cleanup_at).toLocaleString('ru')}
                  . Отложенных удалений с сохранением прежней отсрочки:{' '}
                  {preview.impact.queued_grace_jobs_preserved ?? 0}.
                </p>
              )}
              <p>Подтверждение разрешает применение новой политики.</p>
            </>
          )}
        </div>
      )}
      <button
        disabled={
          busy ||
          !current ||
          !Object.keys(changes).length ||
          (section === 'admin' && !reason.trim())
        }
        onClick={save}
      >
        {busy
          ? 'Сохраняем…'
          : section === 'admin'
            ? preview
              ? 'Подтвердить изменения'
              : 'Проверить изменения'
            : 'Сохранить'}
      </button>
      {section === 'admin' && (
        <details>
          <summary>История и восстановление настроек</summary>
          <button
            className="secondary"
            disabled={busy}
            onClick={async () => {
              try {
                setHistory((await api('/admin/settings/history')).items)
              } catch (e) {
                setError(e.message)
              }
            }}
          >
            Загрузить историю настроек
          </button>
          {history.map((row) => (
            <article className="queue-row" key={row.revision}>
              <strong>Ревизия {row.revision}</strong>
              <small>
                {row.status} · {new Date(row.created_at).toLocaleString('ru')}
              </small>
              <p>{row.reason}</p>
            </article>
          ))}
          <form
            onSubmit={async (e) => {
              e.preventDefault()
              setBusy(true)
              setError('')
              try {
                const result = await write('/admin/settings/rollback', {
                  expected_revision: current.desired_revision,
                  target_revision: Number(targetRevision),
                  reason: rollbackReason,
                })
                setCurrent(result)
                setChanges({})
                setPreview(null)
                setTargetRevision('')
                setRollbackReason('')
                onChanged?.()
                setHistory((await api('/admin/settings/history')).items)
              } catch (e) {
                setError(e.message)
                if (e.code === 'VERSION_CONFLICT')
                  setCurrent(e.details?.current || (await api(prefix)))
              } finally {
                setBusy(false)
              }
            }}
          >
            <p>
              Восстановление создаёт новую ревизию. Для сокращения срока хранения используйте форму
              параметров с проверкой последствий.
            </p>
            <label>
              Целевая ревизия
              <input
                type="number"
                min="1"
                step="1"
                required
                value={targetRevision}
                onChange={(e) => setTargetRevision(e.target.value)}
              />
            </label>
            <label>
              Причина восстановления настроек
              <input
                required
                maxLength={500}
                value={rollbackReason}
                onChange={(e) => setRollbackReason(e.target.value)}
              />
            </label>
            <button disabled={busy || !current || !targetRevision || !rollbackReason.trim()}>
              Восстановить ревизию
            </button>
          </form>
        </details>
      )}
      {admin && (
        <details>
          <summary>Диагностика</summary>
          <button
            className="secondary"
            onClick={async () => {
              try {
                setDiagnostics(await api('/admin/health'))
              } catch (e) {
                setError(e.message)
              }
            }}
          >
            Проверить сервисы
          </button>
          {diagnostics && <pre>{JSON.stringify(diagnostics, null, 2)}</pre>}
        </details>
      )}
    </section>
  )
}
