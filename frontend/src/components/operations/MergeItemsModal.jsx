import { randomId } from '../../utils/id'
import { useEffect, useRef, useState } from 'react'
import { api, write } from '../../api/client'
import { submitConfirmation } from '../../api/confirmations'
import { formatBalance, scaled } from '../../utils/quantity'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'
import { Thumbnail } from '../ui/Thumbnail'

export function MergeItemsModal({ source, target, locations, onClose, onSuccess, onSwap }) {
  const [destination, setDestination] = useState('')
  const [places, setPlaces] = useState([])
  const [review, setReview] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const accepted = useRef(null)
  useEffect(() => {
    const controller = new AbortController()
    api(`/items/${target.id}`, { signal: controller.signal })
      .then((item) => {
        const active = new Set(item.lots.filter((lot) => !lot.archived_at).map((lot) => lot.id))
        setPlaces([
          ...new Set(
            item.balances
              .filter((b) => active.has(b.lot_id) && b.quantity != null && scaled(b.quantity) > 0n)
              .map((b) => b.location_id),
          ),
        ])
      })
      .catch((cause) => {
        if (cause.name !== 'AbortError') setError(cause.message)
      })
    return () => controller.abort()
  }, [target.id])
  useEffect(() => {
    let disposed = false,
      proposal
    const cancel = () => {
      if (proposal?.status === 'editable' && accepted.current !== proposal.proposal_id)
        write(`/proposals/${proposal.proposal_id}/cancel`, {}).catch(() => {})
    }
    api('/proposals/manual', {
      method: 'POST',
      body: {
        client_request_id: randomId(),
        actions: [
          {
            type: 'merge_items',
            values: {
              source_item_id: source.id,
              target_item_id: target.id,
              target_location_id: destination || null,
            },
          },
        ],
      },
    })
      .then((result) => {
        proposal = result
        if (disposed) cancel()
        else setReview(result)
      })
      .catch((cause) => {
        if (!disposed) setError(cause.message)
      })
    return () => {
      disposed = true
      cancel()
    }
  }, [source.id, target.id, destination])
  async function confirm() {
    if (lock.current || !review?.can_confirm) return
    lock.current = true
    setBusy(true)
    setError('')
    try {
      await submitConfirmation(`/proposals/${review.proposal_id}/confirm`, {
        expected_revision: review.revision,
        observed_review_hash: review.review_hash,
        changes: [],
      })
      accepted.current = review.proposal_id
      onSuccess()
      onClose()
    } catch (cause) {
      if (cause.pending) {
        accepted.current = review.proposal_id
        onClose()
        return
      }
      if (cause.review) setReview(cause.review)
      setError(cause.message)
    } finally {
      setBusy(false)
      lock.current = false
    }
  }
  const preview = review?.actions?.[0]?.preview
  return (
    <Modal isOpen title="Объединить вещи" busy={busy} onClose={onClose}>
      <div className="page-stack">
        <p>
          Переложить весь остаток «{source.name}» в «{target.name}»?
        </p>
        {onSwap && (
          <Button variant="text" disabled={busy} onClick={onSwap}>
            Поменять местами источник и цель
          </Button>
        )}
        <div className="toolbar">
          <Thumbnail
            mediaId={target.photos?.find((p) => p.thumbnail)?.thumbnail.media_id}
            alt={`Останется фото: ${target.name}`}
          />
          <p>
            Останутся название и фото целевой вещи. Исходная карточка уйдёт в архив; история
            сохранится.
          </p>
        </div>
        {places.length > 1 && (
          <Select
            label="Место целевой вещи"
            value={destination}
            disabled={busy}
            onChange={(event) => {
              setReview(null)
              setError('')
              setDestination(event.target.value)
            }}
          >
            <option value="">Выберите место</option>
            {places.map((id) => (
              <option key={id} value={id}>
                {locations.find((p) => p.id === id)?.full_path || id}
              </option>
            ))}
          </Select>
        )}
        {!review && !error && <p role="status">Проверяем совместимость…</p>}
        {review?.blocking_issues?.map((issue, index) => (
          <p className="notice" key={index}>
            {issue.message}
          </p>
        ))}
        {review?.can_confirm && (
          <p className="notice">
            В месте «{preview.location_label}» будет:{' '}
            {formatBalance(
              { quantity: preview.target_after, quantity_state: preview.quantity_state },
              target.base_unit_id,
              target.attributes?.counting_unit,
            )}
          </p>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="actions">
          <Button variant="secondary" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
          <Button disabled={busy || !review?.can_confirm} onClick={confirm}>
            {busy ? 'Сохраняем…' : 'Да, объединить весь остаток'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
