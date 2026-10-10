import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useResource } from '../hooks/useResource'
import { usePaged } from '../hooks/usePaged'
import { Button } from '../components/ui/Button'
import { Thumbnail } from '../components/ui/Thumbnail'
import { Modal } from '../components/ui/Modal'
import { StockOperationsModal } from '../components/operations/StockOperationsModal'
import { ReceiveStockModal } from '../components/operations/ReceiveStockModal'
import { ItemOperationsModal } from '../components/operations/ItemOperationsModal'
import { EditItemModal } from '../components/operations/EditItemModal'
import { LotOperationsModal } from '../components/operations/LotOperationsModal'
import { formatQuantity, formatBalance, scaled } from '../utils/quantity'
import { label } from '../utils/labels'
import { describeValue } from '../utils/display'
import { ItemReviewStatus } from '../components/ItemReviewStatus'
import { useTaskRefresh } from '../hooks/useTaskRefresh'
import { visibleStocks } from '../utils/editItem'

export function ItemDetail() {
  const { id } = useParams()
  return <Detail key={id} id={id} />
}
function Detail({ id }) {
  const resource = useResource(`/items/${id}`),
    locations = useResource('/locations')
  const aliases = useResource(`/items/${id}/aliases`),
    history = usePaged(`/items/${id}/history?limit=20`)
  const itemFields = useResource('/item-fields')
  useTaskRefresh(resource.reload)
  const [tab, setTab] = useState('lots'),
    [modal, setModal] = useState(null),
    [photo, setPhoto] = useState(null)
  const item = resource.data,
    places = locations.data?.items || []
  function reload() {
    resource.reload()
    aliases.reload()
    history.reload()
  }
  if (!item)
    return (
      <div className="stack">
        <Link to="/items">К каталогу</Link>
        <p role={resource.error ? 'alert' : 'status'}>{resource.error?.message || 'Загрузка…'}</p>
        <Button onClick={reload}>Обновить</Button>
      </div>
    )
  const active = item.lifecycle === 'active'
  const locationName = (id) => places.find((row) => row.id === id)?.full_path || id
  const common = {
    isOpen: true,
    item,
    locations: places,
    onClose: () => setModal(null),
    onSuccess: reload,
  }
  return (
    <div className="stack">
      <Link to="/items">К каталогу</Link>
      {[resource.error, locations.error, aliases.error].filter(Boolean).map((e, i) => (
        <p role="alert" key={i}>
          {e.message}
        </p>
      ))}
      <section className="card stack">
        <div className="toolbar">
          <h1>{item.name}</h1>
          <ItemReviewStatus item={item} />
          {!active && <span className="badge">В архиве</span>}
        </div>
        <p>
          {label(item.primary_category)} · {formatQuantity(item)} · {label(item.privacy_policy)}
        </p>
        <div className="photo-strip">
          {item.photos?.map((row) => (
            <button
              type="button"
              key={row.media_id}
              aria-label="Открыть фотографию"
              onClick={() => setPhoto(row)}
            >
              <Thumbnail mediaId={row.thumbnail?.media_id} alt={item.name} />
            </button>
          ))}
        </div>
        <div className="actions">
          {active ? (
            <>
              <Button onClick={() => setModal({ type: 'edit' })}>Редактировать</Button>
              {!['untracked', 'individual'].includes(item.tracking_mode) && (
                <Button onClick={() => setModal({ type: 'receive' })}>Пополнить</Button>
              )}
              <details className="action-menu">
                <summary>Ещё</summary>
                <div className="actions">
                  <Button
                    variant="secondary"
                    onClick={() => setModal({ type: 'item', operation: 'archive' })}
                  >
                    В архив
                  </Button>
                  <Link className="btn btn-secondary" to={`/capture?item_id=${id}`}>
                    Фото или голос для этой вещи
                  </Link>
                </div>
              </details>
            </>
          ) : (
            <Button onClick={() => setModal({ type: 'item', operation: 'restore' })}>
              Восстановить
            </Button>
          )}
        </div>
      </section>
      <nav className="tabs" aria-label="Карточка вещи">
        {[
          ['lots', 'Где и сколько'],
          ['data', 'Описание'],
          ['history', 'История'],
        ].map(([value, title]) => (
          <Button
            key={value}
            variant={tab === value ? 'primary' : 'secondary'}
            aria-pressed={tab === value}
            onClick={() => setTab(value)}
          >
            {title}
          </Button>
        ))}
      </nav>
      {tab === 'lots' && (
        <div className="stack">
          {item.lots
            .filter((lot) => !lot.archived_at)
            .map((lot) => (
              <section className="card stack" key={lot.id}>
                {(lot.label || lot.serial_number) && <h2>{lot.label || lot.serial_number}</h2>}
                <p>
                  Срок:{' '}
                  {lot.expiry_precision === 'month'
                    ? `до конца ${lot.expiry_on?.slice(0, 7)}`
                    : lot.effective_expiry_on || lot.expiry_on || 'неизвестен'}
                  {lot.opened_on && ` · Открыто ${lot.opened_on}`}
                </p>
                {visibleStocks(item)
                  .filter((balance) => balance.lot_id === lot.id)
                  .map((balance) => (
                    <div className="balance-row" key={balance.id}>
                      <Link to={`/locations/${balance.location_id}`}>
                        {locationName(balance.location_id)}
                      </Link>
                      <strong>
                        {formatBalance(balance, item.base_unit_id, item.attributes?.counting_unit)}
                      </strong>
                      {active && (
                        <div className="actions">
                          {[
                            ['move', 'Переместить'],
                            ['consume', 'Списать'],
                            ['set_quantity', 'Уточнить остаток'],
                            ['confirm_presence', 'Подтвердить наличие'],
                          ].map(([operation, title]) => (
                            <Button
                              key={operation}
                              variant="secondary"
                              disabled={
                                (operation === 'consume' && balance.quantity == null) ||
                                (['consume', 'move'].includes(operation) &&
                                  balance.quantity != null &&
                                  scaled(balance.quantity) === 0n)
                              }
                              onClick={() => setModal({ type: 'stock', operation, lot, balance })}
                            >
                              {title}
                            </Button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                {active && (
                  <details>
                    <summary>Срок и свойства</summary>
                    <div className="actions">
                      {[['update', 'Изменить сведения']].map(([operation, title]) => (
                        <Button
                          key={operation}
                          variant="text"
                          disabled={
                            (operation !== 'update' &&
                              ['untracked', 'individual'].includes(item.tracking_mode)) ||
                            (operation === 'merge' &&
                              item.lots.filter((row) => !row.archived_at).length < 2) ||
                            (operation === 'split' &&
                              !item.balances.some(
                                (balance) =>
                                  balance.lot_id === lot.id &&
                                  balance.quantity != null &&
                                  scaled(balance.quantity) > 0n,
                              ))
                          }
                          onClick={() => setModal({ type: 'lot', operation, lot })}
                        >
                          {title}
                        </Button>
                      ))}
                    </div>
                  </details>
                )}
              </section>
            ))}
          {!item.lots.length && <p>Место и количество пока не указаны.</p>}
        </div>
      )}
      {tab === 'data' && (
        <section className="card stack">
          <h2>Описание</h2>
          <p>{item.user_description || 'Описание не указано'}</p>
          {item.ocr_text && (
            <details>
              <summary>Полный текст OCR</summary>
              <pre className="ocr-text">{item.ocr_text}</pre>
            </details>
          )}
          {item.generated_description && <p>Описание модели: {item.generated_description}</p>}
          <dl>
            {[
              ['Марка', item.brand],
              ['Модель', item.model],
              ['Штрихкод', item.barcode],
              ['Метки', item.tags?.join(', ')],
              ...Object.entries(item.attributes || {}),
              ...Object.entries(item.custom_attributes || {}).map(([key, value]) => [
                itemFields.data?.custom_fields.find((field) => field.key === key)?.label || key,
                value,
              ]),
            ].map(
              ([key, value]) =>
                value != null && (
                  <div key={key}>
                    <dt>{label(key)}</dt>
                    <dd>{describeValue(value, key)}</dd>
                  </div>
                ),
            )}
          </dl>
          <h3>Поисковые синонимы</h3>
          {aliases.data?.items.map((alias) => (
            <div className="actions" key={alias.id}>
              {alias.alias}
              <Button
                variant="text"
                onClick={() => setModal({ type: 'item', operation: 'remove_alias', alias })}
              >
                Удалить синоним
              </Button>
            </div>
          ))}
          {active && (
            <Button
              variant="secondary"
              onClick={() => setModal({ type: 'item', operation: 'add_alias' })}
            >
              Добавить синоним
            </Button>
          )}
        </section>
      )}
      {tab === 'history' && (
        <section className="stack">
          <h2>История операций</h2>
          {history.error && <p role="alert">{history.error.message}</p>}
          {history.items.map((operation) => (
            <Link className="card" key={operation.id} to={`/operations/${operation.id}`}>
              {label(operation.command_type || operation.type || operation.source)} ·{' '}
              {new Date(operation.created_at).toLocaleString()} · {label(operation.status)}
            </Link>
          ))}
          {!history.items.length && !history.loading && <p>Операций пока нет.</p>}
          {history.next_cursor && (
            <Button onClick={history.more} disabled={history.loading}>
              Ещё
            </Button>
          )}
        </section>
      )}
      {modal?.type === 'receive' && <ReceiveStockModal {...common} />}
      {modal?.type === 'edit' && <EditItemModal {...common} />}
      {modal?.type === 'stock' && (
        <StockOperationsModal
          {...common}
          operation={modal.operation}
          initialLot={modal.lot}
          initialBalance={modal.balance}
        />
      )}
      {modal?.type === 'item' && (
        <ItemOperationsModal {...common} operation={modal.operation} alias={modal.alias} />
      )}
      {modal?.type === 'lot' && (
        <LotOperationsModal {...common} operation={modal.operation} lot={modal.lot} />
      )}
      {photo && (
        <Modal isOpen title="Фотография вещи" onClose={() => setPhoto(null)}>
          <Thumbnail mediaId={photo.media_id} alt={item.name} full />
        </Modal>
      )}
    </div>
  )
}
