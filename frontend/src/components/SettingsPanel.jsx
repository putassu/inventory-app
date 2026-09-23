import { useEffect, useState } from 'react'
import { api, write } from '../api/client'
import { Input } from './ui/Input'
import { Select } from './ui/Select'
import { Button } from './ui/Button'
export function SettingsPanel({ admin = false }) {
  const prefix = admin ? '/admin/settings' : '/settings'
  const [definition, setDefinition] = useState([])
  const [current, setCurrent] = useState(null)
  const [changes, setChanges] = useState({})
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState(null)
  const [impact, setImpact] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [history, setHistory] = useState([])
  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      api(`${prefix}/schema`, { signal: controller.signal }),
      api(prefix, { signal: controller.signal }),
    ])
      .then(([schema, state]) => {
        setDefinition(schema.fields)
        setCurrent(state)
      })
      .catch((cause) => {
        if (cause.name !== 'AbortError') setError(cause.message)
      })
    return () => controller.abort()
  }, [prefix])
  function change(field, raw) {
    let value = raw
    if (field.type === 'int' || field.type === 'float') value = raw === '' ? null : Number(raw)
    setChanges((previous) => ({ ...previous, [field.key]: value }))
    setPreview(null)
    setImpact(false)
  }
  async function submit() {
    setBusy(true)
    setError('')
    const body = {
      changes: Object.entries(changes).map(([key, value]) => ({ key, value })),
      ...(admin
        ? {
            expected_revision: current.desired_revision,
            reason: reason.trim(),
            impact_confirmed: impact,
          }
        : { expected_version: current.version }),
    }
    try {
      if (admin && !reason.trim()) throw new Error('Укажите причину изменения.')
      if (admin && !preview) {
        setPreview(await write(`${prefix}/validate`, body))
        return
      }
      setCurrent(await write(prefix, body, 'PATCH'))
      setChanges({})
      setPreview(null)
      setImpact(false)
    } catch (cause) {
      setError(cause.message)
      if (cause.status === 409) {
        setCurrent(await api(prefix))
        setPreview(null)
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="page-stack">
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!current && !error && <p>Загрузка настроек…</p>}
      {current && (
        <>
          {admin && (
            <p className="notice">
              Желаемая ревизия: {current.desired_revision}. Действующая:{' '}
              {current.effective_revision}.{' '}
              {current.status === 'pending_restart' &&
                `Ожидают перезапуска: ${current.components_pending.join(', ')}.`}
            </p>
          )}
          <div className="settings-list">
            {definition.map((field) => {
              const value = Object.hasOwn(changes, field.key)
                ? changes[field.key]
                : (current.desired || current.values)[field.key]
              const title = field.description_ru || field.key
              return (
                <div key={field.key}>
                  {field.type === 'bool' ? (
                    <label className="check">
                      <input
                        type="checkbox"
                        disabled={busy || field.editable === false}
                        checked={!!value}
                        onChange={(event) => change(field, event.target.checked)}
                      />
                      {title}
                    </label>
                  ) : field.enum?.length ? (
                    <Select
                      label={title}
                      value={value ?? ''}
                      disabled={busy || field.editable === false}
                      onChange={(event) => change(field, event.target.value)}
                    >
                      {field.enum.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Input
                      label={title}
                      value={value ?? ''}
                      type={['int', 'float'].includes(field.type) ? 'number' : 'text'}
                      step={field.type === 'int' ? '1' : 'any'}
                      disabled={busy || field.editable === false}
                      onChange={(event) => change(field, event.target.value)}
                    />
                  )}
                  {field.editable === false && <small>{field.disabled_reason}</small>}
                  {admin && (
                    <small>
                      {field.apply_mode === 'requires_restart'
                        ? 'После перезапуска'
                        : field.apply_mode === 'immediate'
                          ? 'Сразу'
                          : 'Для новых задач'}{' '}
                      · Сейчас: {String(current.effective?.[field.key] ?? '')}
                    </small>
                  )}
                </div>
              )
            })}
          </div>
          {admin && (
            <Input
              label="Причина изменения"
              value={reason}
              onChange={(event) => {
                setReason(event.target.value)
                setPreview(null)
              }}
            />
          )}
          {preview && (
            <div className="notice">
              <p>Параметры проверены. Подтвердите применение.</p>
              {preview.impact && (
                <pre className="json-output">{JSON.stringify(preview.impact, null, 2)}</pre>
              )}
              {preview.retention_reduced?.length > 0 && (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={impact}
                    onChange={(event) => setImpact(event.target.checked)}
                  />
                  Подтверждаю сокращение сроков хранения: {preview.retention_reduced.join(', ')}
                </label>
              )}
            </div>
          )}
          <Button
            disabled={
              busy ||
              !Object.keys(changes).length ||
              (preview?.retention_reduced?.length > 0 && !impact)
            }
            onClick={submit}
          >
            {busy ? 'Сохранение…' : admin && !preview ? 'Проверить изменения' : 'Применить'}
          </Button>
          {admin && (
            <>
              <Button
                variant="secondary"
                onClick={async () => {
                  try {
                    setHistory((await api('/admin/settings/history')).items)
                  } catch (cause) {
                    setError(cause.message)
                  }
                }}
              >
                История настроек
              </Button>
              {history.map((revision) => (
                <div className="card toolbar" key={revision.revision}>
                  <span>
                    Ревизия {revision.revision}: {revision.reason}
                  </span>
                  <Button
                    variant="secondary"
                    disabled={busy || !reason.trim()}
                    onClick={async () => {
                      setBusy(true)
                      try {
                        setCurrent(
                          await write('/admin/settings/rollback', {
                            expected_revision: current.desired_revision,
                            target_revision: revision.revision,
                            reason,
                          }),
                        )
                        setChanges({})
                        setPreview(null)
                      } catch (cause) {
                        setError(cause.message)
                      } finally {
                        setBusy(false)
                      }
                    }}
                  >
                    Откатить с указанной причиной
                  </Button>
                </div>
              ))}
            </>
          )}
        </>
      )}
    </div>
  )
}
