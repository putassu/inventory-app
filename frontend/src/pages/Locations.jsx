import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useResource } from '../hooks/useResource'
import { moveLocation } from '../api/commands'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Thumbnail } from '../components/ui/Thumbnail'
import { LocationOperationsModal } from '../components/operations/LocationOperationsModal'
import { TreeView } from '../components/ui/TreeView'
import { descendants, isSystemLocation } from '../utils/locations'
import { formatBalance } from '../utils/quantity'

function Contents({ location, recursive }) {
  const places = useResource('/locations')
  const allowed = recursive
    ? descendants(places.data?.items || [], location.id)
    : new Set([location.id])
  const { data, error, loading, reload } = useResource(
    `/locations/${location.id}/contents?recursive=${recursive}`,
  )
  if (loading) return <p role="status">Загрузка содержимого…</p>
  if (error)
    return (
      <p role="alert">
        {error.message} <Button onClick={reload}>Повторить</Button>
      </p>
    )
  return (
    <div className="location-contents">
      {!data.items.length && <p>В этом месте пока нет вещей.</p>}
      {data.items.map((item) => (
        <Link className="item-row" to={`/items/${item.id}`} key={item.id}>
          <Thumbnail
            mediaId={item.photos?.find((photo) => photo.thumbnail)?.thumbnail.media_id}
            alt={item.name}
            size={40}
          />
          <span>
            <strong>{item.name}</strong>
            <br />
            {item.balances
              .filter((balance) => allowed.has(balance.location_id))
              .map((balance) => (
                <small key={balance.id}>
                  {formatBalance(balance, item.base_unit_id)}
                  {recursive
                    ? ` · ${places.data?.items.find((place) => place.id === balance.location_id)?.full_path || location.name}`
                    : ''}
                  <br />
                </small>
              ))}
          </span>
        </Link>
      ))}
    </div>
  )
}
function LocationRow({ location, onAction, busy }) {
  const [open, setOpen] = useState(false)
  const [recursive, setRecursive] = useState(false)
  return (
    <Card className="location-card">
      <div className="toolbar">
        <button
          type="button"
          className="location-name"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <strong>{location.name}</strong>
          <small>
            {location.kind === 'container'
              ? 'Контейнер'
              : isSystemLocation(location)
                ? 'Системное место'
                : 'Место'}{' '}
            · {location.full_path}
          </small>
        </button>
        <div className="toolbar">
          <Link to={`/locations/${location.id}`}>Открыть</Link>
          {!isSystemLocation(location) && (
            <>
              <Button
                disabled={busy}
                variant="secondary"
                onClick={() => onAction('create', { parent_id: location.id })}
              >
                Добавить потомка
              </Button>
              <Button
                disabled={busy}
                variant="secondary"
                onClick={() => onAction('update', location)}
              >
                Изменить
              </Button>
              <Button
                disabled={busy}
                variant="secondary"
                onClick={() => onAction('move', location)}
              >
                Переместить
              </Button>
              <Button disabled={busy} variant="text" onClick={() => onAction('archive', location)}>
                В архив
              </Button>
            </>
          )}
        </div>
      </div>
      {open && (
        <>
          <label className="check">
            <input
              type="checkbox"
              checked={recursive}
              onChange={(event) => setRecursive(event.target.checked)}
            />
            Включить вложенные места
          </label>
          <Contents
            key={`${location.version}:${recursive}`}
            location={location}
            recursive={recursive}
          />
        </>
      )}
    </Card>
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
        <Button variant="secondary" onClick={reload}>
          Обновить
        </Button>
      </div>
      <Input
        label="Поиск места"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {(error || failure) && (
        <p role="alert" className="error">
          {error?.message || failure}
        </p>
      )}
      {busy && <p role="status">Подтверждено, ожидаем сохранения…</p>}
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
              busy={busy}
              onAction={(operation, row) => setModal({ operation, location: row })}
            />
          )}
        />
      )}
      {modal && (
        <LocationOperationsModal
          isOpen
          {...modal}
          locations={data?.items || []}
          onClose={() => setModal(null)}
          onSuccess={reload}
        />
      )}
    </section>
  )
}
export function LocationDetail() {
  const { id } = useParams()
  const { data, error, loading } = useResource(`/locations/${id}`)
  const [recursive, setRecursive] = useState(false)
  return (
    <section className="page-stack">
      <Link to="/locations">← Места</Link>
      <h1>{data?.name || 'Место хранения'}</h1>
      {loading && <p>Загрузка…</p>}
      {error && <p role="alert">{error.message}</p>}
      {data && (
        <>
          <p>{data.full_path}</p>
          <p>{data.description}</p>
          <label className="check">
            <input
              type="checkbox"
              checked={recursive}
              onChange={(event) => setRecursive(event.target.checked)}
            />
            Включить вложенные места
          </label>
          <Contents location={data} recursive={recursive} />
        </>
      )}
    </section>
  )
}
