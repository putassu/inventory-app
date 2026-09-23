import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { executeBulkCommands, archiveItemsBulk } from '../api/commands'
import { onConfirmation } from '../api/confirmations'
import { usePaged } from '../hooks/usePaged'
import { useResource } from '../hooks/useResource'
import { useTasks } from '../contexts/TaskContext'
import { formatQuantity, scaled } from '../utils/quantity'
import { label } from '../utils/labels'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { Thumbnail } from '../components/ui/Thumbnail'
import { Modal } from '../components/ui/Modal'
import { ReceiveStockModal } from '../components/operations/ReceiveStockModal'

function Catalog({ path, locations, grid, onNew }) {
  const page = usePaged(path)
  const { reload } = page
  const [selected, setSelected] = useState(new Set())
  const [operation, setOperation] = useState(null)
  const [destination, setDestination] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(
    () =>
      onConfirmation((receipt) => {
        if (receipt.status === 'applied') reload()
      }),
    [reload],
  )
  const items = page.items.map((item) => ({
    ...item,
    id: item.id || item.item_id,
    primary_category: item.primary_category || item.category,
    base_unit_id: item.base_unit_id || item.unit_code,
    lifecycle: item.lifecycle || 'active',
  }))
  async function submit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const details = []
      for (const id of selected) details.push(await api(`/items/${id}`))
      if (operation === 'archive') await archiveItemsBulk(details)
      else {
        const actions = []
        const versions = {}
        for (const item of details) {
          versions[`item:${item.id}`] = item.version
          const activeLots = new Set(
            item.lots
              .filter((lot) => !lot.archived_at)
              .map((lot) => {
                versions[`lot:${lot.id}`] = lot.version
                return lot.id
              }),
          )
          for (const balance of item.balances) {
            if (
              !activeLots.has(balance.lot_id) ||
              balance.location_id === destination ||
              (['exact', 'estimated'].includes(balance.quantity_state) &&
                scaled(balance.quantity) === 0n)
            )
              continue
            versions[`balance:${balance.id}`] = balance.version
            actions.push({
              type: 'move_stock',
              values: {
                lot_id: balance.lot_id,
                location_id: balance.location_id,
                to_location_id: destination || null,
                whole_presence: true,
              },
            })
          }
        }
        if (!actions.length) throw new Error('Нет остатков для переноса в выбранное место.')
        await executeBulkCommands(actions, versions)
      }
      setSelected(new Set())
      setOperation(null)
      page.reload()
    } catch (cause) {
      setError(cause.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      {selected.size > 0 && (
        <div className="toolbar notice">
          <strong>Выбрано: {selected.size}</strong>
          <Button onClick={() => setOperation('move')}>Переместить выбранные</Button>
          <Button variant="secondary" onClick={() => setOperation('archive')}>
            В архив
          </Button>
          <Button variant="text" onClick={() => setSelected(new Set())}>
            Снять выбор
          </Button>
        </div>
      )}
      {page.warning && <p className="notice">{page.warning}</p>}
      {page.error && (
        <p role="alert" className="error">
          {page.error.message} <Button onClick={page.reload}>Повторить</Button>
        </p>
      )}
      {page.loading && <p role="status">Загрузка каталога…</p>}
      {!page.loading && !page.error && !items.length && (
        <div className="card">
          <p>Вещей по выбранным условиям пока нет.</p>
          <Button onClick={onNew}>Добавить вручную</Button>{' '}
          <Link to="/capture">Фото или голос</Link>
        </div>
      )}
      <div className={grid ? 'catalog-grid' : 'page-stack'}>
        {items.map((item) => (
          <article key={item.id} className="card item-row">
            <input
              type="checkbox"
              aria-label={`Выбрать ${item.name}`}
              checked={selected.has(item.id)}
              onChange={() =>
                setSelected((previous) => {
                  const next = new Set(previous)
                  if (next.has(item.id)) next.delete(item.id)
                  else next.add(item.id)
                  return next
                })
              }
            />
            <Thumbnail
              mediaId={item.photos?.find((photo) => photo.thumbnail)?.thumbnail.media_id}
              alt={item.name}
              size={grid ? 96 : 56}
            />
            <div className="item-summary">
              <div className="toolbar">
                <Link to={`/items/${item.id}`}>
                  <strong>{item.name}</strong>
                </Link>
                <span className={`status-badge status-${item.lifecycle}`}>
                  {label(item.lifecycle)}
                </span>
              </div>
              <small>
                {label(item.primary_category)}
                {item.brand && ` · ${item.brand}`}
                {item.model && ` · ${item.model}`}
                {item.photos?.length > 1 && ` · Фото: ${item.photos.length}`}
              </small>
              <p>{formatQuantity(item)}</p>
              <small>
                {[
                  ...new Set(
                    (item.balances || item.lots || [])
                      .map(
                        (balance) =>
                          balance.location_path ||
                          locations.find((location) => location.id === balance.location_id)
                            ?.full_path,
                      )
                      .filter(Boolean),
                  ),
                ].join('; ')}
              </small>
              {item.explanation_short && <p className="muted">{item.explanation_short}</p>}
            </div>
          </article>
        ))}
      </div>
      {page.next_cursor && (
        <Button variant="secondary" disabled={page.loading} onClick={page.more}>
          Загрузить ещё
        </Button>
      )}
      <Modal
        isOpen={!!operation}
        busy={busy}
        onClose={() => setOperation(null)}
        title={operation === 'move' ? 'Массовое перемещение' : 'Архивация выбранных вещей'}
      >
        <form onSubmit={submit} className="page-stack">
          <p>
            Выбрано вещей: {selected.size}. Изменение применится одной операцией после проверки
            сервером.
          </p>
          {operation === 'move' ? (
            <Select
              label="Куда переместить"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            >
              <option value="">Место не указано</option>
              {locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.full_path}
                </option>
              ))}
            </Select>
          ) : (
            <p>Архив скроет карточки из обычного списка. Остатки и история сохранятся.</p>
          )}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? 'Ожидание сохранения…' : 'Подтвердить'}
          </Button>
        </form>
      </Modal>
    </>
  )
}
export function Items() {
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [availability, setAvailability] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [grid, setGrid] = useState(false)
  const [receive, setReceive] = useState(false)
  const [version, setVersion] = useState(0)
  const { data: locationData } = useResource('/locations')
  const { data: categories } = useResource('/reference/categories')
  const { activeTasks = [] } = useTasks()
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300)
    return () => clearTimeout(timer)
  }, [search])
  const params = new URLSearchParams({ limit: '30' })
  if (query) params.set('query', query)
  if (category) params.set('category', category)
  if (availability) params.set('availability', availability)
  if (!query) params.set('include_archived', String(includeArchived))
  const path = `${query ? '/search' : '/items'}?${params}`
  const reviews = activeTasks.filter((task) => task.status === 'waiting_for_review')
  return (
    <section className="page-stack">
      <div className="toolbar">
        <h1>Каталог вещей</h1>
        <Link className="btn btn-secondary" to="/capture">
          Фото / Голос (AI)
        </Link>
        <Button onClick={() => setReceive(true)}>Поступление вручную</Button>
      </div>
      {reviews.length > 0 && (
        <div className="notice">
          <strong>Черновики / на проверке: {reviews.length}</strong>
          <p>Изменения ещё не применены к каталогу.</p>
          {reviews.slice(0, 5).map((task) => (
            <Link className="review-link" key={task.task_id} to={`/review/${task.proposal_id}`}>
              {task.title || 'Проверить предложение'}{' '}
              <span className="status-badge">На проверке</span>
            </Link>
          ))}
        </div>
      )}
      <Input
        label="Поиск по подтверждённому каталогу"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') setQuery(search.trim())
        }}
      />
      <div className="toolbar">
        <Select
          label="Категория"
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          <option value="">Все категории</option>
          {categories?.items.map((row) => (
            <option key={row.code} value={row.code}>
              {row.name}
            </option>
          ))}
        </Select>
        <Select
          label="Наличие"
          value={availability}
          onChange={(event) => setAvailability(event.target.value)}
        >
          <option value="">Все остатки</option>
          <option value="available">В наличии</option>
          <option value="depleted">Закончилось</option>
        </Select>
        <label className="check">
          <input
            type="checkbox"
            disabled={!!query}
            checked={includeArchived && !query}
            onChange={(event) => setIncludeArchived(event.target.checked)}
          />
          Включить архивные
        </label>
        <Button variant="secondary" onClick={() => setGrid(!grid)}>
          {grid ? 'Список' : 'Сетка фото'}
        </Button>
      </div>
      {query && includeArchived && (
        <p className="notice">
          Поиск выполняется среди активных вещей. Очистите поиск для просмотра архива.
        </p>
      )}
      <Catalog
        key={`${path}:${version}`}
        path={path}
        locations={locationData?.items || []}
        grid={grid}
        onNew={() => setReceive(true)}
      />
      {receive && (
        <ReceiveStockModal
          isOpen
          onClose={() => setReceive(false)}
          onSuccess={() => setVersion((value) => value + 1)}
          locations={locationData?.items || []}
        />
      )}
    </section>
  )
}
