import { useId, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useResource } from '../hooks/useResource'
import { moveLocation } from '../api/commands'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Thumbnail } from '../components/ui/Thumbnail'
import { Modal } from '../components/ui/Modal'
import { LocationOperationsModal } from '../components/operations/LocationOperationsModal'
import { ReceiveStockModal } from '../components/operations/ReceiveStockModal'
import { PendingItems } from '../components/PendingItems'
import { TreeView } from '../components/ui/TreeView'
import { descendants, isSystemLocation } from '../utils/locations'
import { formatBalance } from '../utils/quantity'
import { useItemDrag } from '../hooks/useItemDrag'
import { MergeItemsModal } from '../components/operations/MergeItemsModal'
import { ItemReviewStatus } from '../components/ItemReviewStatus'
import { useTaskRefresh } from '../hooks/useTaskRefresh'

const placeType = (location) =>
  location.kind === 'container'
    ? '📦 Контейнер'
    : isSystemLocation(location)
      ? '📍 Без места'
      : '🏠 Стационарное место'
function Contents({ location, recursive, places }) {
  const drag = useItemDrag()
  const allowed = recursive ? descendants(places, location.id) : new Set([location.id])
  const { data, error, loading, reload } = useResource(
    `/locations/${location.id}/contents?recursive=${recursive}`,
  )
  useTaskRefresh(reload)
  return (
    <div className="location-contents page-stack">
      <PendingItems locationIds={allowed} />
      {drag.error && (
        <p role="alert" className="error">
          {drag.error}
        </p>
      )}
      {loading && <p role="status">Загрузка…</p>}
      {error && (
        <p role="alert">
          {error.message} <Button onClick={reload}>Повторить</Button>
        </p>
      )}
      {data && !data.items.length && <p className="muted">Добавьте первую вещь в это место.</p>}
      {data?.items.map((item) => (
        <Link
          className="card item-row"
          to={`/items/${item.id}`}
          key={item.id}
          {...drag.dragProps(item)}
        >
          <Thumbnail
            mediaId={item.photos?.find((photo) => photo.thumbnail)?.thumbnail.media_id}
            alt={item.name}
            size={56}
          />
          <span className="item-summary">
            <strong>{item.name}</strong>
            <ItemReviewStatus item={item} link={false} />
            <br />
            {item.balances
              .filter((balance) => allowed.has(balance.location_id))
              .map((balance) => (
                <small key={balance.id}>
                  {formatBalance(balance, item.base_unit_id, item.attributes?.counting_unit)}
                  {recursive
                    ? ` · ${places.find((place) => place.id === balance.location_id)?.full_path || location.name}`
                    : ''}
                  <br />
                </small>
              ))}
          </span>
        </Link>
      ))}
      {drag.merge && (
        <MergeItemsModal
          key={drag.merge[0].id + drag.merge[1].id}
          source={drag.merge[0]}
          target={drag.merge[1]}
          locations={places}
          onSwap={() => drag.setMerge([drag.merge[1], drag.merge[0]])}
          onClose={() => drag.setMerge(null)}
          onSuccess={reload}
        />
      )}
    </div>
  )
}
function PlaceActions({ location, onAction, busy }) {
  return (
    <div className="toolbar">
      <Button disabled={busy} onClick={() => onAction('receive', location)}>
        Добавить вещь
      </Button>
      {!isSystemLocation(location) && (
        <details className="action-menu">
          <summary>Ещё</summary>
          <div className="page-stack">
            <Button
              disabled={busy}
              variant="text"
              onClick={() => onAction('create', { parent_id: location.id })}
            >
              Добавить секцию или контейнер
            </Button>
            <Button disabled={busy} variant="text" onClick={() => onAction('update', location)}>
              Изменить / добавить фото
            </Button>
            <Button disabled={busy} variant="text" onClick={() => onAction('move', location)}>
              Переместить
            </Button>
            <Button disabled={busy} variant="text" onClick={() => onAction('archive', location)}>
              В архив
            </Button>
          </div>
        </details>
      )}
    </div>
  )
}
function ContentsDisclosure({ location, places, initiallyOpen = false }) {
  const [open, setOpen] = useState(initiallyOpen)
  const [recursive, setRecursive] = useState(false)
  const id = useId()
  return (
    <div className="page-stack location-disclosure">
      <Button
        variant="secondary"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        {open ? 'Скрыть вещи' : 'Показать вещи'}
      </Button>
      <div id={id} hidden={!open}>
        {open && (
          <div className="page-stack">
            <label className="check">
              <input
                type="checkbox"
                checked={recursive}
                onChange={(event) => setRecursive(event.target.checked)}
              />
              Включить вложенные места
            </label>
            <Contents
              key={String(recursive)}
              location={location}
              recursive={recursive}
              places={places}
            />
          </div>
        )}
      </div>
    </div>
  )
}
function PlaceModal({ modal, places, onClose, onSuccess }) {
  if (!modal) return null
  return modal.operation === 'receive' ? (
    <ReceiveStockModal
      isOpen
      initialLocationId={modal.location.id}
      locations={places}
      onClose={onClose}
      onSuccess={onSuccess}
    />
  ) : (
    <LocationOperationsModal
      isOpen
      {...modal}
      locations={places}
      onClose={onClose}
      onSuccess={onSuccess}
    />
  )
}
function LocationRow({ location, places, onAction, busy }) {
  return (
    <div className="card location-card">
      <div className="toolbar">
        <Link className="location-name item-row" to={`/locations/${location.id}`}>
          <Thumbnail
            mediaId={location.photos?.find((photo) => photo.thumbnail)?.thumbnail.media_id}
            alt={location.name}
            size={56}
          />
          <span className="item-summary">
            <strong>{location.name}</strong>
            <small>{placeType(location)}</small>
          </span>
        </Link>
        <PlaceActions location={location} onAction={onAction} busy={busy} />
      </div>
      <ContentsDisclosure location={location} places={places} />
    </div>
  )
}
export function Locations() {
  const { data, error, loading, reload } = useResource('/locations')
  const [search, setSearch] = useState('')
  const [modal, setModal] = useState(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  async function move(id, parentId) {
    setBusy(true)
    setFailure('')
    try {
      const location = data.items.find((row) => row.id === id)
      await moveLocation(
        { location_id: id, parent_id: parentId },
        { [`location:${id}`]: location.version },
      )
      reload()
      return true
    } catch (cause) {
      setFailure(cause.message)
      return false
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="page-stack">
      <div className="toolbar">
        <h1>Места хранения</h1>
        <Button onClick={() => setModal({ operation: 'create', location: null })}>
          Добавить место
        </Button>
      </div>
      <Input
        label="Найти место"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {(error || failure) && (
        <p role="alert" className="error">
          {error?.message || failure}
        </p>
      )}
      {busy && <p role="status">Сохраняем…</p>}
      {loading && <p>Загрузка мест…</p>}
      {data && (
        <TreeView
          items={data.items}
          search={search}
          busy={busy}
          onMove={move}
          renderItem={(location) => (
            <LocationRow
              location={location}
              places={data.items}
              busy={busy}
              onAction={(operation, row) => setModal({ operation, location: row })}
            />
          )}
        />
      )}
      <PlaceModal
        modal={modal}
        places={data?.items || []}
        onClose={() => setModal(null)}
        onSuccess={reload}
      />
    </section>
  )
}
export function LocationDetail() {
  const { id } = useParams()
  return <Detail key={id} id={id} />
}
function Detail({ id }) {
  const navigate = useNavigate()
  const { data, error, loading, reload } = useResource(`/locations/${id}`)
  const places = useResource('/locations')
  const [modal, setModal] = useState(null)
  const [photo, setPhoto] = useState(null)
  const [version, setVersion] = useState(0)
  function updated() {
    if (modal?.operation === 'archive') {
      navigate(data?.parent_id ? `/locations/${data.parent_id}` : '/locations')
      return
    }
    reload()
    places.reload()
    setVersion((value) => value + 1)
  }
  const rows = places.data?.items || []
  return (
    <section className="page-stack">
      <Link to={data?.parent_id ? `/locations/${data.parent_id}` : '/locations'}>
        ← {rows.find((row) => row.id === data?.parent_id)?.name || 'Все места'}
      </Link>
      {loading && <p>Загрузка…</p>}
      {error && (
        <p role="alert">
          {error.message} <Link to="/locations">К местам</Link>
        </p>
      )}
      {data && (
        <>
          <div className="toolbar">
            <h1>{data.name}</h1>
            <span className="badge">{placeType(data)}</span>
          </div>
          <p className="muted">{data.full_path}</p>
          {data.description && <p>{data.description}</p>}
          {!!data.photos?.length && (
            <div className="photo-strip">
              {data.photos.map((row) => (
                <Button
                  key={row.media_id}
                  variant="text"
                  aria-label="Открыть фото места"
                  onClick={() => setPhoto(row.media_id)}
                >
                  <Thumbnail mediaId={row.thumbnail?.media_id} size={96} alt={data.name} />
                </Button>
              ))}
            </div>
          )}
          <PlaceActions
            location={data}
            onAction={(operation, row) => setModal({ operation, location: row })}
          />
          <div className="location-children">
            {rows
              .filter((row) => row.parent_id === id)
              .map((row) => (
                <Link className="card item-row" to={`/locations/${row.id}`} key={row.id}>
                  <Thumbnail
                    mediaId={row.photos?.find((p) => p.thumbnail)?.thumbnail.media_id}
                    size={40}
                    alt={row.name}
                  />
                  <span>
                    {row.name}
                    <small>{placeType(row)}</small>
                  </span>
                </Link>
              ))}
          </div>
          <ContentsDisclosure key={version} location={data} places={rows} initiallyOpen />
        </>
      )}
      <PlaceModal modal={modal} places={rows} onClose={() => setModal(null)} onSuccess={updated} />
      <Modal isOpen={!!photo} title="Фото места" onClose={() => setPhoto(null)}>
        {photo && <Thumbnail mediaId={photo} full alt="Фото места" />}
      </Modal>
    </section>
  )
}
