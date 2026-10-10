import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { executeBulkCommands, archiveItemsBulk } from '../api/commands'
import { onConfirmation } from '../api/confirmations'
import { usePaged } from '../hooks/usePaged'
import { useResource } from '../hooks/useResource'
import { useTasks } from '../contexts/TaskContext'
import { formatQuantity, scaled } from '../utils/quantity'
import { label, reviewLabels } from '../utils/labels'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { Thumbnail } from '../components/ui/Thumbnail'
import { Modal } from '../components/ui/Modal'
import { ReceiveStockModal } from '../components/operations/ReceiveStockModal'
import { PendingItems } from '../components/PendingItems'
import { ItemReviewStatus } from '../components/ItemReviewStatus'
import { MergeItemsModal } from '../components/operations/MergeItemsModal'
import { useItemDrag } from '../hooks/useItemDrag'

function Catalog({ path, locations, grid, onNew, selected, setSelected, pendingQuery }) {
  const page = usePaged(path)
  const { activeTasks = [] } = useTasks()
  const { reload } = page
  const taskVersion = activeTasks.map((task) => `${task.task_id}:${task.status_version}`).join(',')
  useEffect(() => {
    reload()
  }, [taskVersion, reload])
  const [operation, setOperation] = useState(null)
  const [destination, setDestination] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { dragProps, merge, setMerge, error: dragError } = useItemDrag(busy)
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
  const visibleItems = new Map(items.map((item) => [item.id, item]))
  const pinned = [...selected.values()].map((item) => visibleItems.get(item.id) || item)
  const results = items.filter((item) => !selected.has(item.id))
  async function submit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const details = []
      for (const id of selected.keys()) details.push(await api(`/items/${id}`))
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
                to_location_id: destination,
                whole_presence: true,
              },
            })
          }
        }
        if (!actions.length) throw new Error('Нет остатков для переноса в выбранное место.')
        await executeBulkCommands(actions, versions)
      }
      setSelected(new Map())
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
      {dragError && (
        <p role="alert" className="error">
          {dragError}
        </p>
      )}
      {selected.size > 0 && (
        <div className="toolbar notice">
          <strong>Выбрано: {selected.size}</strong>
          {selected.size === 2 && (
            <Button variant="secondary" onClick={() => setMerge([...selected.values()])}>
              Объединить две вещи
            </Button>
          )}
          <Button onClick={() => setOperation('move')}>Переместить выбранные</Button>
          <Button variant="secondary" onClick={() => setOperation('archive')}>
            В архив
          </Button>
          <Button variant="text" disabled={busy} onClick={() => setSelected(new Map())}>
            Снять выбор
          </Button>
        </div>
      )}
      {[
        { title: 'Выбранные вещи', rows: pinned },
        { title: 'Результаты', rows: results },
      ].map(
        ({ title, rows }) =>
          (rows.length > 0 || title === 'Результаты') && (
            <section
              key={title}
              className={`page-stack ${title === 'Выбранные вещи' ? 'selected-items' : ''}`}
              aria-label={title}
            >
              {selected.size > 0 && <h2>{title}</h2>}
              {title === 'Результаты' && (
                <>
                  {pendingQuery != null && <PendingItems query={pendingQuery} />}
                  {page.warning && <p className="notice">{page.warning}</p>}
                  {items.length > 0 &&
                    items.every((item) => item.matched_by === 'dense_sparse_rrf') && (
                      <p className="notice">
                        Точных текстовых совпадений нет. Показаны возможные совпадения по смыслу —
                        проверьте карточки.
                      </p>
                    )}
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
                </>
              )}
              <div className={grid ? 'catalog-grid' : 'page-stack'}>
                {rows.map((item) => (
                  <article key={item.id} className="card item-row" {...dragProps(item)}>
                    <input
                      type="checkbox"
                      aria-label={`Выбрать ${item.name}`}
                      checked={selected.has(item.id)}
                      disabled={busy}
                      onChange={() =>
                        setSelected((previous) => {
                          const next = new Map(previous)
                          if (next.has(item.id)) next.delete(item.id)
                          else next.set(item.id, item)
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
                        <ItemReviewStatus item={item} />
                        {item.lifecycle === 'archived' && (
                          <span className="status-badge">В архиве</span>
                        )}
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
                              .filter(
                                (balance) =>
                                  !['exact', 'estimated'].includes(balance.quantity_state) ||
                                  balance.quantity == null ||
                                  scaled(balance.quantity) > 0n,
                              )
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
                      {item.explanation_short && (
                        <p className="muted">
                          {item.matched_by === 'dense_sparse_rrf'
                            ? 'Возможное совпадение по смыслу'
                            : item.explanation_short}
                        </p>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ),
      )}
      {page.next_cursor && (
        <Button variant="secondary" disabled={page.loading} onClick={page.more}>
          Загрузить ещё
        </Button>
      )}
      {merge && (
        <MergeItemsModal
          key={merge[0].id + merge[1].id}
          source={merge[0]}
          target={merge[1]}
          locations={locations}
          onSwap={() => setMerge([merge[1], merge[0]])}
          onClose={() => setMerge(null)}
          onSuccess={() => {
            setSelected(new Map())
            page.reload()
          }}
        />
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
              required
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            >
              <option value="" disabled>
                Выберите место
              </option>
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
  const [selected, setSelected] = useState(new Map())
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [reviewStatus, setReviewStatus] = useState('')
  const [sort, setSort] = useState('newest')
  const [availability, setAvailability] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [grid, setGrid] = useState(false)
  const [receive, setReceive] = useState(false)
  const [version, setVersion] = useState(0)
  const { data: locationData } = useResource('/locations')
  const { data: categories } = useResource('/reference/categories')
  const { data: preferences } = useResource('/settings')
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300)
    return () => clearTimeout(timer)
  }, [search])
  const params = new URLSearchParams({ limit: '30', sort })
  if (reviewStatus) params.set('review_status', reviewStatus)
  if (query) params.set('query', query)
  if (category) params.set('category', category)
  if (availability) params.set('availability', availability)
  if (!query) params.set('include_archived', String(includeArchived))
  const path = `${query ? '/search' : '/items'}?${params}`
  return (
    <section className={`page-stack${preferences?.values?.compact_view ? ' compact-catalog' : ''}`}>
      <div className="toolbar">
        <h1>Мои вещи</h1>
        <Link className="btn btn-secondary" to="/capture">
          По фото или голосу
        </Link>
        <Button onClick={() => setReceive(true)}>Добавить вещь</Button>
      </div>
      <Input
        label="Найти вещь"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') setQuery(search.trim())
        }}
      />
      <details>
        <summary>Фильтры и вид</summary>
        <div className="toolbar">
          <Select label="Сортировка" value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="newest">Сначала новые</option>
            <option value="oldest">Сначала старые</option>
            <option value="name_asc">Название: А–Я</option>
            <option value="name_desc">Название: Я–А</option>
            <option value="status">Статус: сначала ошибки</option>
            <option value="expiry">Ближайший срок</option>
          </Select>
          <Select
            label="Проверка карточки"
            value={reviewStatus}
            onChange={(event) => setReviewStatus(event.target.value)}
          >
            <option value="">Все статусы</option>
            {Object.entries(reviewLabels).map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </Select>
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
      </details>
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
        selected={selected}
        setSelected={setSelected}
        pendingQuery={!category && !availability && !reviewStatus ? query : null}
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
