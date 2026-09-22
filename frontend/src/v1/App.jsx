import { useCallback, useEffect, useRef, useState } from 'react'
import { allPages, api, restoreSession, setSession, write } from './api'
import Review from './Review'
import Settings from './Settings'
import './app.css'

const statusNames = {
  accepted: 'Принято',
  preparing: 'Подготовка',
  queued: 'В очереди',
  running: 'Распознавание',
  retry_wait: 'Ожидает повтора',
  waiting_for_review: 'Проверьте результат',
  applying: 'Сохраняется',
  succeeded: 'Готово',
  failed: 'Ошибка',
  cancelled: 'Отменено',
  expired: 'Срок проверки истёк',
}
const commandNames = {
  receive_stock: 'Добавить предмет / пополнить',
  move_stock: 'Переместить остаток',
  consume_stock: 'Израсходовать',
  set_quantity: 'Установить количество',
  update_item: 'Изменить карточку',
  update_lot: 'Изменить партию',
  split_lot: 'Разделить партию',
  merge_lots: 'Объединить партии',
  create_location: 'Создать место',
  move_location: 'Переместить место',
  update_location: 'Изменить место',
  archive_location: 'Архивировать место',
  archive_item: 'Архивировать предмет',
  restore_item: 'Восстановить предмет',
  add_alias: 'Добавить название',
  remove_alias: 'Удалить название',
  confirm_presence: 'Подтвердить наличие',
}

function Login({ onLogin }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <main className="login">
      <form
        className="panel"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError('')
          const data = new FormData(e.currentTarget)
          try {
            const result = await write('/auth/login', {
              login: data.get('login'),
              password: data.get('password'),
              client_type: 'web',
            })
            setSession(result.access_token)
            onLogin(await api('/me'))
          } catch (error) {
            setError(error.message)
          } finally {
            setBusy(false)
          }
        }}
      >
        <p className="eyebrow">Всё на своём месте</p>
        <h1>Инвентаризатор</h1>
        <p>Ваши вещи, остатки и сроки.</p>
        <label>
          Логин
          <input name="login" autoComplete="username" required />
        </label>
        <label>
          Пароль
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button disabled={busy}>{busy ? 'Входим…' : 'Войти'}</button>
      </form>
    </main>
  )
}

function Capture({ onCreated, capabilities }) {
  const [files, setFiles] = useState([])
  const [text, setText] = useState('')
  const [local, setLocal] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [requestId, setRequestId] = useState(crypto.randomUUID())
  const [uploaded, setUploaded] = useState([])
  const privacyChosen = useRef(false)
  useEffect(() => {
    let active = true
    api('/settings')
      .then((settings) => {
        if (active && !privacyChosen.current)
          setLocal(settings.values?.default_privacy !== 'cloud_allowed')
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])
  async function submit(e) {
    e.preventDefault()
    privacyChosen.current = true
    setBusy(true)
    setError('')
    try {
      if (files.filter((file) => file.type.startsWith('audio/')).length > 1)
        throw new Error('На одну задачу можно выбрать одну аудиозапись.')
      const media = [...uploaded]
      for (let i = media.length; i < files.length; i++) {
        const form = new FormData()
        form.set('file', files[i])
        form.set('privacy_policy', local ? 'local_only' : 'cloud_allowed')
        media.push(await api('/media', { method: 'POST', body: form, key: `${requestId}:${i}` }))
        setUploaded([...media])
      }
      const images = media.filter((m) => m.type === 'image').map((m) => m.media_id)
      const audio = media.find((m) => m.type === 'audio')?.media_id || null
      await write(
        '/tasks',
        {
          client_request_id: requestId,
          input_mode: audio
            ? images.length
              ? 'photo_audio'
              : 'audio'
            : images.length
              ? 'photo'
              : 'text',
          text: text || null,
          media_ids: images,
          audio_media_id: audio,
          privacy: { force_local: local },
        },
        'POST',
        requestId,
      )
      setFiles([])
      setUploaded([])
      setText('')
      setRequestId(crypto.randomUUID())
      onCreated()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="panel" onSubmit={submit}>
      <h2>Добавить по фото или описанию</h2>
      <p>Результат появится в очереди проверки. Учёт изменится после вашего подтверждения.</p>
      <label>
        Описание
        <textarea
          rows="3"
          disabled={busy}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Что добавляем, сколько и куда…"
        />
      </label>
      <label>
        Фотографии{capabilities?.audio_inference && ' или WAV'}
        <input
          key={requestId}
          type="file"
          multiple
          disabled={busy}
          accept={
            capabilities?.audio_inference
              ? 'image/jpeg,image/png,image/webp,audio/wav,audio/x-wav'
              : 'image/jpeg,image/png,image/webp'
          }
          onChange={(e) => {
            setFiles([...e.target.files])
            setUploaded([])
            setRequestId(crypto.randomUUID())
          }}
        />
      </label>
      <small>
        {files.length
          ? `Выбрано файлов: ${files.length}`
          : 'Несколько фотографий одного предмета будут объединены.'}
      </small>
      {!capabilities?.audio_inference && (
        <p className="muted">Голос недоступен: сервер не подтвердил поддержку аудио.</p>
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={local}
          disabled={busy || !!uploaded.length}
          onChange={(e) => {
            privacyChosen.current = true
            setLocal(e.target.checked)
          }}
        />
        Только локальная обработка
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button disabled={busy || (!text.trim() && !files.length)}>
        {busy ? 'Загружаем…' : 'Отправить на распознавание'}
      </button>
    </form>
  )
}

function SelectTarget({ selection, onSelect, onClose }) {
  const [ids, setIds] = useState([])
  const multiple = selection.type === 'merge_lots'
  return (
    <section className="panel">
      <h2>{commandNames[selection.type]}</h2>
      <label>
        {multiple ? 'Выберите минимум две партии одного предмета' : 'Выберите запись'}
        <select
          multiple={multiple}
          value={multiple ? ids : ids[0] || ''}
          onChange={(e) =>
            setIds([...e.target.selectedOptions].map((o) => o.value).filter(Boolean))
          }
        >
          {!multiple && <option value="">Не выбрано</option>}
          {selection.rows.map((row) => (
            <option key={row.id} value={row.id}>
              {row.label}
            </option>
          ))}
        </select>
      </label>
      <div className="actions">
        <button disabled={ids.length < (multiple ? 2 : 1)} onClick={() => onSelect(ids)}>
          Открыть форму
        </button>
        <button className="quiet" onClick={onClose}>
          Закрыть
        </button>
      </div>
    </section>
  )
}

function Item({ item, locations, onCommand, onHistory, onDelete }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <article className="card">
      <button
        className="item-title"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        <span>
          <strong>{item.name}</strong>
          <small>{item.lifecycle === 'archived' ? 'В архиве' : item.primary_category}</small>
        </span>
        <span className="amount">
          {item.tracking_mode === 'untracked'
            ? item.depleted
              ? 'Нет'
              : 'Есть'
            : `${item.known_quantity ?? '—'}${item.has_unknown_quantity ? ' + ?' : ''}`}
          <small>{item.base_unit_id}</small>
        </span>
      </button>
      {expanded && (
        <div className="item-detail">
          {item.lots
            ?.filter((lot) => !lot.archived_at)
            .map((lot) => (
              <div className="lot" key={lot.id}>
                <strong>{lot.label || 'Партия'}</strong>
                {lot.effective_expiry_on && <span> · До {lot.effective_expiry_on}</span>}
                <button
                  className="quiet"
                  onClick={() => onCommand('update_lot', { lot_id: lot.id })}
                >
                  Изменить партию
                </button>
                {item.balances
                  .filter((balance) => balance.lot_id === lot.id)
                  .map((balance) => (
                    <div key={balance.id}>
                      <p>
                        {locations.find((l) => l.id === balance.location_id)?.full_path ||
                          'Место не указано'}{' '}
                        ·{' '}
                        {balance.quantity_state === 'unknown'
                          ? 'Количество неизвестно'
                          : (balance.quantity ?? 'Наличие')}{' '}
                        {item.base_unit_id}
                      </p>
                      <div className="actions compact">
                        {[
                          'move_stock',
                          'consume_stock',
                          'set_quantity',
                          'split_lot',
                          'confirm_presence',
                        ].map((type) => (
                          <button
                            key={type}
                            className="secondary"
                            onClick={() =>
                              onCommand(type, { lot_id: lot.id, location_id: balance.location_id })
                            }
                          >
                            {commandNames[type]}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            ))}
          <div className="actions compact">
            <button
              className="secondary"
              onClick={() => onCommand('receive_stock', { item_id: item.id })}
            >
              Пополнить
            </button>
            <button
              className="secondary"
              onClick={() => onCommand('update_item', { item_id: item.id })}
            >
              Изменить
            </button>
            <button
              className="secondary"
              onClick={() => onCommand('add_alias', { item_id: item.id })}
            >
              Другое название
            </button>
            <button className="quiet" onClick={() => onHistory(item)}>
              История
            </button>
            <button
              className="quiet"
              onClick={() =>
                onCommand(item.lifecycle === 'archived' ? 'restore_item' : 'archive_item', {
                  item_id: item.id,
                })
              }
            >
              {item.lifecycle === 'archived' ? 'Восстановить' : 'В архив'}
            </button>
            {item.lifecycle === 'archived' && (
              <button className="danger" onClick={() => onDelete(item)}>
                Удалить навсегда…
              </button>
            )}
          </div>
        </div>
      )}
    </article>
  )
}

export default function App() {
  const [user, setUser] = useState(undefined)
  const [tab, setTab] = useState('items')
  const [rows, setRows] = useState([])
  const [cursor, setCursor] = useState(null)
  const [locations, setLocations] = useState([])
  const [review, setReview] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [archive, setArchive] = useState(false)
  const [capabilities, setCapabilities] = useState(null)
  const [command, setCommand] = useState('receive_stock')
  const [history, setHistory] = useState(null)
  const [deletion, setDeletion] = useState(null)
  const [exportJob, setExportJob] = useState(null)
  const [selection, setSelection] = useState(null)
  const [purgeJobs, setPurgeJobs] = useState([])
  const [selectedReviews, setSelectedReviews] = useState([])
  const [compact, setCompact] = useState(false)
  const taskRows = useRef([])
  const [generation, setGeneration] = useState(0)
  const reload = useCallback(() => setGeneration((n) => n + 1), [])
  const signedIn = useCallback((person) => {
    setSession(undefined, person.workspaces[0]?.id)
    setUser(person)
  }, [])
  useEffect(() => {
    restoreSession()
      .then(signedIn)
      .catch(() => setUser(null))
  }, [signedIn])
  useEffect(() => {
    if (!user) return
    api('/capabilities')
      .then(setCapabilities)
      .catch((e) => setError(e.message))
    api('/locations')
      .then((r) => setLocations(r.items))
      .catch((e) => setError(e.message))
    api('/settings')
      .then((settings) => setCompact(!!settings.values?.compact_view))
      .catch(() => {})
    api('/purge-jobs')
      .then((r) => setPurgeJobs(r.items))
      .catch((e) => setError(e.message))
  }, [user, generation])
  useEffect(() => {
    if (!user || ['settings', 'capture'].includes(tab)) return
    let cancelled = false,
      timer,
      loading = false,
      lastListAt = 0
    const paths = {
      items: '/items?include_archived=' + archive,
      locations: '/locations',
      review: '/review-inbox',
      tasks: '/tasks',
      notifications: '/notifications',
      operations: '/operations',
    }
    const load = async (force = false) => {
      if (loading || cancelled) return
      if (document.hidden && !force) {
        timer = setTimeout(load, 15000)
        return
      }
      loading = true
      let interval = 4000
      try {
        if (tab === 'tasks' && !force && Date.now() - lastListAt < 30000) {
          const active = taskRows.current.filter((task) => task.poll_after_ms != null)
          const changed = []
          for (let offset = 0; offset < active.length; offset += 100) {
            const result = await api('/tasks/status', {
              method: 'POST',
              body: {
                tasks: active
                  .slice(offset, offset + 100)
                  .map((task) => ({ task_id: task.task_id, status_version: task.status_version })),
              },
            })
            changed.push(...result.changed)
            interval = Math.max(1000, Math.min(10000, result.poll_after_ms || 4000))
          }
          if (!cancelled && changed.length) {
            const updates = new Map(changed.map((task) => [task.task_id, task]))
            taskRows.current = taskRows.current.map((task) => updates.get(task.task_id) || task)
            setRows(taskRows.current)
          }
        } else {
          const result = await api(paths[tab])
          if (cancelled) return
          if (tab === 'tasks') taskRows.current = result.items
          setRows(result.items)
          setCursor(result.next_cursor)
          lastListAt = Date.now()
        }
        if (!cancelled) {
          setError('')
        }
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        loading = false
      }
      if (!cancelled && ['review', 'tasks', 'notifications'].includes(tab))
        timer = setTimeout(load, interval)
    }
    const onVisible = () => {
      if (!document.hidden) {
        clearTimeout(timer)
        load(true)
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    load(true)
    return () => {
      cancelled = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [user, tab, generation, archive])
  useEffect(() => {
    if (!exportJob || ['succeeded', 'failed', 'expired', 'revoked'].includes(exportJob.status))
      return
    const timer = setTimeout(
      () =>
        api('/exports/' + exportJob.export_id)
          .then(setExportJob)
          .catch((e) => setError(e.message)),
      1500,
    )
    return () => clearTimeout(timer)
  }, [exportJob])
  async function manual(type = command, supplied = {}) {
    try {
      const values = { ...supplied }
      const targetKind =
        type === 'merge_lots' || type === 'update_lot'
          ? 'lot'
          : type === 'update_item' || type === 'restore_item'
            ? 'item'
            : type === 'update_location'
              ? 'location'
              : null
      if (targetKind && !(values.lot_ids || values[targetKind + '_id'])) {
        const items =
          targetKind === 'location' ? [] : await allPages('/items?include_archived=true')
        const targets =
          targetKind === 'location'
            ? locations.map((location) => ({ id: location.id, label: location.full_path }))
            : targetKind === 'item'
              ? items.map((item) => ({ id: item.id, label: item.name }))
              : items.flatMap((item) =>
                  item.lots
                    .filter((lot) => !lot.archived_at)
                    .map((lot) => ({
                      id: lot.id,
                      label: `${item.name} · ${lot.label || lot.serial_number || 'Партия'} · ${lot.effective_expiry_on || 'Срок не указан'}`,
                    })),
                )
        setSelection({ type, kind: targetKind, rows: targets })
        return
      }
      if (type === 'receive_stock' && values.item_id) values.item_mode = 'existing'
      if (type.startsWith('update_')) {
        const kind = type.slice(7)
        const row = await api(
          `/${kind === 'location' ? 'locations' : kind === 'item' ? 'items' : 'lots'}/${values[kind + '_id']}`,
        )
        const keys = {
          item: [
            'name',
            'primary_category',
            'attributes',
            'tags',
            'barcode',
            'brand',
            'model',
            'user_description',
            'privacy_policy',
          ],
          location: ['name', 'description', 'default_privacy_policy'],
          lot: [
            'label',
            'serial_number',
            'manufacturer_batch',
            'acquired_at',
            'manufactured_on',
            'opened_on',
            'expiry_on',
            'expiry_precision',
            'expiry_raw_text',
            'after_opening_amount',
            'after_opening_unit',
            'lot_attributes',
            'privacy_policy',
          ],
        }[kind]
        for (const key of keys) if (row[key] !== undefined) values[key] = row[key]
      }
      setReview(
        await write('/proposals/manual', {
          actions: [{ action_id: 'a1', type, values }],
          client_request_id: crypto.randomUUID(),
        }),
      )
      setSelection(null)
    } catch (e) {
      setError(e.message)
    }
  }
  async function openReview(id) {
    try {
      setReview(await api('/proposals/' + id))
    } catch (e) {
      setError(e.message)
    }
  }
  async function run(action) {
    try {
      setError('')
      await action()
    } catch (e) {
      setError(e.message)
    }
  }
  if (user === undefined)
    return (
      <main className="login">
        <p>Открываем инвентарь…</p>
      </main>
    )
  if (!user) return <Login onLogin={signedIn} />
  const tabs = {
    items: 'Предметы',
    locations: 'Места',
    capture: 'Добавить',
    review: 'Проверить',
    tasks: 'Задачи',
    notifications: 'Уведомления',
    operations: 'Журнал',
    settings: 'Настройки',
  }
  return (
    <div className={'shell' + (compact ? ' compact-view' : '')}>
      <aside>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault()
            setTab('items')
          }}
        >
          ▦ <span>Инвентаризатор</span>
        </a>
        <p className="workspace">{user.workspaces[0]?.name}</p>
        <nav>
          {Object.entries(tabs).map(([key, name]) => (
            <button
              key={key}
              className={tab === key ? 'active' : ''}
              onClick={() => {
                setRows([])
                setCursor(null)
                setSelectedReviews([])
                setTab(key)
                setError('')
                setNotice('')
                setHistory(null)
                setQuery('')
              }}
            >
              {name}
            </button>
          ))}
        </nav>
        <div className="account">
          <span>{user.login}</span>
          <button
            className="quiet"
            onClick={() =>
              run(async () => {
                await write('/auth/logout', {})
                setSession(null, null)
                setUser(null)
              })
            }
          >
            Выйти
          </button>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">Личный инвентарь</p>
            <h1>{tabs[tab]}</h1>
          </div>
          <button onClick={() => manual('receive_stock')}>+ Вручную</button>
        </header>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {!user.agreements.some((a) => a.type === 'trusted_server') && (
          <div className="notice">
            <p>
              Файлы и описания обрабатывает доверенный сервер владельца. Внешние модели управляются
              отдельным разрешением.
            </p>
            <button
              onClick={() =>
                run(async () => {
                  await write('/me/agreements', { agreement_type: 'trusted_server', version: '1' })
                  signedIn(await api('/me'))
                })
              }
            >
              Принимаю условия обработки сервером
            </button>
          </div>
        )}
        {review && (
          <Review
            initial={review}
            key={review.proposal_id + ':' + review.revision}
            onClose={() => setReview(null)}
            onSaved={reload}
          />
        )}
        {selection && (
          <SelectTarget
            key={selection.type}
            selection={selection}
            onClose={() => setSelection(null)}
            onSelect={(ids) =>
              manual(
                selection.type,
                selection.type === 'merge_lots'
                  ? { lot_ids: ids }
                  : { [selection.kind + '_id']: ids[0] },
              )
            }
          />
        )}
        {tab === 'items' &&
          archive &&
          purgeJobs
            .filter((job) => job.status === 'queued')
            .map((job) => (
              <section className="panel" key={job.purge_job_id}>
                <strong>Ожидает окончательного удаления</strong>
                <p>
                  Удаление после {new Date(job.not_before).toLocaleDateString('ru')}. До этого можно
                  восстановить карточки.
                </p>
                <button
                  className="secondary"
                  onClick={() =>
                    run(async () => {
                      await write(`/purge-jobs/${job.purge_job_id}/cancel`, {
                        expected_version: job.version,
                        explicit_confirmation: true,
                      })
                      reload()
                      setNotice('Удаление отменено, карточки восстановлены.')
                    })
                  }
                >
                  Отменить удаление
                </button>
              </section>
            ))}
        {tab === 'capture' && (
          <Capture
            capabilities={capabilities}
            onCreated={() => {
              setTab('tasks')
              reload()
            }}
          />
        )}
        {tab === 'settings' && (
          <Settings admin={['owner', 'admin'].includes(user.app_role)} onChanged={reload} />
        )}
        {tab === 'items' && (
          <>
            <form
              className="search"
              onSubmit={(e) => {
                e.preventDefault()
                run(async () => {
                  const result = await api('/search?query=' + encodeURIComponent(query))
                  setRows(
                    await Promise.all(result.items.map((item) => api('/items/' + item.item_id))),
                  )
                  setCursor(null)
                  setNotice(result.warning || '')
                })
              }}
            >
              <input
                aria-label="Поиск предметов"
                placeholder="Название, другое название, код…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <button>Найти</button>
              <button
                type="button"
                className="quiet"
                onClick={() => {
                  setQuery('')
                  reload()
                }}
              >
                Сбросить
              </button>
            </form>
            <div className="toolbar">
              <label className="check">
                <input
                  type="checkbox"
                  checked={archive}
                  onChange={(e) => setArchive(e.target.checked)}
                />
                Показать архив
              </label>
              <button
                className="quiet"
                onClick={() =>
                  run(async () =>
                    setExportJob(
                      await write('/exports', {
                        format: 'zip',
                        include_media: true,
                        include_history: true,
                      }),
                    ),
                  )
                }
              >
                Экспорт ZIP
              </button>
            </div>
            {exportJob && (
              <p className="notice">
                {exportJob.status === 'succeeded' ? (
                  <button
                    className="quiet"
                    onClick={() =>
                      run(async () => {
                        const blob = await api(exportJob.download, { blob: true })
                        const url = URL.createObjectURL(blob)
                        const link = document.createElement('a')
                        link.href = url
                        link.download = 'inventory.zip'
                        link.click()
                        setTimeout(() => URL.revokeObjectURL(url), 1000)
                      })
                    }
                  >
                    Скачать экспорт
                  </button>
                ) : exportJob.status === 'failed' ? (
                  'Экспорт не выполнен'
                ) : ['expired', 'revoked'].includes(exportJob.status) ? (
                  'Экспорт больше недоступен. Создайте новый экспорт.'
                ) : (
                  'Экспорт готовится…'
                )}
              </p>
            )}
            {rows.map((item) => (
              <Item
                key={item.id || item.item_id}
                item={item}
                locations={locations}
                onCommand={manual}
                onHistory={(item) =>
                  run(async () =>
                    setHistory({ ...(await api(`/items/${item.id}/history`)), item_id: item.id }),
                  )
                }
                onDelete={(item) =>
                  run(async () =>
                    setDeletion(await write('/deletion-previews', { item_ids: [item.id] })),
                  )
                }
              />
            ))}
          </>
        )}
        {tab === 'locations' && (
          <>
            <button className="secondary" onClick={() => manual('create_location')}>
              Добавить место
            </button>
            {rows.map((location) => (
              <article className="card row" key={location.id}>
                <span>
                  <strong>{location.full_path}</strong>
                  <small>{location.is_unspecified ? 'Системное место' : ''}</small>
                </span>
                {!location.is_unspecified && (
                  <div className="actions compact">
                    <button
                      className="quiet"
                      onClick={() => manual('update_location', { location_id: location.id })}
                    >
                      Изменить
                    </button>
                    <button
                      className="quiet"
                      onClick={() => manual('move_location', { location_id: location.id })}
                    >
                      Переместить
                    </button>
                    <button
                      className="quiet"
                      onClick={() => manual('archive_location', { location_id: location.id })}
                    >
                      Архивировать
                    </button>
                  </div>
                )}
              </article>
            ))}
          </>
        )}
        {tab === 'review' && (
          <div className="toolbar">
            <p>Выбрано предложений: {selectedReviews.length}</p>
            <button
              disabled={selectedReviews.length < 2}
              onClick={() =>
                run(async () => {
                  const sources = rows
                    .filter((row) => selectedReviews.includes(row.proposal_id))
                    .map((row) => ({ proposal_id: row.proposal_id, revision: row.revision }))
                  setReview(await write('/review-batches', { sources }))
                  setSelectedReviews([])
                })
              }
            >
              Объединить для общей проверки
            </button>
          </div>
        )}
        {tab === 'review' &&
          rows.map((row) => (
            <article className="card row" key={row.proposal_id}>
              <div>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={selectedReviews.includes(row.proposal_id)}
                    onChange={(e) =>
                      setSelectedReviews((old) =>
                        e.target.checked
                          ? [...old, row.proposal_id]
                          : old.filter((id) => id !== row.proposal_id),
                      )
                    }
                  />
                  В общую проверку
                </label>
                <strong>{row.summary}</strong>
                <small>
                  {row.blocking_count
                    ? `Нужно заполнить: ${row.blocking_count}`
                    : 'Готово к проверке'}
                </small>
              </div>
              <button onClick={() => openReview(row.proposal_id)}>Проверить</button>
            </article>
          ))}
        {tab === 'tasks' &&
          rows.map((task) => (
            <article className="card" key={task.task_id}>
              <div className="row">
                <div>
                  <strong>{statusNames[task.status] || task.status}</strong>
                  <small>
                    {task.progress?.message || new Date(task.created_at).toLocaleString('ru')}
                  </small>
                </div>
                {task.proposal_id && (
                  <button onClick={() => openReview(task.proposal_id)}>Проверить</button>
                )}
              </div>
              {task.error_code && <p className="notice">{task.error_code}</p>}
              <div className="actions compact">
                {task.can_cancel && (
                  <button
                    className="quiet"
                    onClick={() =>
                      run(() => write(`/tasks/${task.task_id}/cancel`, {}).then(reload))
                    }
                  >
                    Отменить
                  </button>
                )}
                {['failed', 'cancelled', 'waiting_for_review'].includes(task.status) && (
                  <button
                    className="quiet"
                    onClick={() =>
                      run(async () => {
                        const result = await write(`/tasks/${task.task_id}/manual-review`, {
                          client_request_id: crypto.randomUUID(),
                        })
                        await openReview(result.proposal_id)
                        reload()
                      })
                    }
                  >
                    Заполнить вручную
                  </button>
                )}
                {['failed', 'cancelled', 'expired'].includes(task.status) && (
                  <button
                    className="quiet"
                    onClick={() =>
                      run(() =>
                        write(`/tasks/${task.task_id}/retry`, {
                          client_request_id: crypto.randomUUID(),
                        }).then(reload),
                      )
                    }
                  >
                    Повторить обработку
                  </button>
                )}
              </div>
            </article>
          ))}
        {tab === 'notifications' &&
          rows.map((row) => (
            <article className="card" key={row.id}>
              <strong>{row.title}</strong>
              <p>{row.body}</p>
              <button
                className="quiet"
                onClick={() =>
                  run(() =>
                    write(
                      `/notifications/${row.id}`,
                      { expected_version: row.version, dismiss: true },
                      'PATCH',
                    ).then(reload),
                  )
                }
              >
                Скрыть
              </button>
            </article>
          ))}
        {(tab === 'operations' ? rows : history?.items || []).map((row) => (
          <article className="card row" key={row.id}>
            <div>
              <strong>
                {commandNames[row.type] || (row.type === 'batch' ? 'Группа действий' : row.type)}
              </strong>
              <small>{new Date(row.applied_at).toLocaleString('ru')}</small>
            </div>
            <button
              className="quiet"
              onClick={() =>
                run(async () => setReview(await write(`/operations/${row.id}/reverse-preview`, {})))
              }
            >
              Предпросмотр отмены
            </button>
          </article>
        ))}
        {tab !== 'operations' && history?.has_more && history.next_cursor && (
          <button
            className="secondary"
            onClick={() =>
              run(async () => {
                const more = await api(
                  `/items/${history.item_id}/history?cursor=${encodeURIComponent(history.next_cursor)}`,
                )
                setHistory((old) => ({ ...old, ...more, items: [...old.items, ...more.items] }))
              })
            }
          >
            Загрузить ещё историю
          </button>
        )}
        {deletion && (
          <section className="panel">
            <h2>Удалить навсегда</h2>
            <p>
              Будут удалены карточки, связанные личные сведения и несвязанные с другими предметами
              файлы. Предпросмотр: {deletion.impact.items?.length ?? 1} карточек.
            </p>
            <button
              className="danger"
              onClick={() =>
                run(async () => {
                  const result = await write('/purge-jobs', {
                    preview_id: deletion.preview_id,
                    preview_revision: deletion.preview_revision,
                    preview_hash: deletion.preview_hash,
                    explicit_confirmation: true,
                  })
                  setDeletion(null)
                  setNotice(
                    'Карточка скрыта. Физическое удаление после ' +
                      new Date(result.not_before).toLocaleDateString('ru'),
                  )
                })
              }
            >
              Подтверждаю удаление
            </button>
            <button className="quiet" onClick={() => setDeletion(null)}>
              Отмена
            </button>
          </section>
        )}
        {cursor && (
          <button
            className="secondary"
            onClick={() =>
              run(async () => {
                const path = {
                  items: '/items?include_archived=' + archive + '&',
                  review: '/review-inbox?',
                  tasks: '/tasks?',
                  operations: '/operations?',
                  notifications: '/notifications?',
                }[tab]
                const result = await api(path + 'cursor=' + encodeURIComponent(cursor))
                if (tab === 'tasks') taskRows.current = [...taskRows.current, ...result.items]
                setRows((old) => [...old, ...result.items])
                setCursor(result.next_cursor)
              })
            }
          >
            Показать ещё
          </button>
        )}
        {!rows.length && !['settings', 'capture'].includes(tab) && (
          <div className="empty">
            <span>▦</span>
            <p>Пока ничего нет</p>
            <small>
              {tab === 'review'
                ? 'Здесь появятся результаты распознавания для вашего подтверждения.'
                : 'Добавьте первый предмет или выберите действие.'}
            </small>
          </div>
        )}
        <details className="panel">
          <summary>Все действия учёта</summary>
          <div className="actions">
            <select
              aria-label="Действие учёта"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
            >
              {Object.entries(commandNames).map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
            <button onClick={() => manual()}>Открыть форму</button>
          </div>
        </details>
      </main>
    </div>
  )
}
