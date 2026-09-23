import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Modal } from '../ui/Modal'
import { previewReverseOperation } from '../../api/commands'
export function ReverseOperationModal({ isOpen, onClose, operationId }) {
  const [result, setResult] = useState(null),
    [error, setError] = useState('')
  useEffect(() => {
    if (!isOpen) return
    let active = true
    previewReverseOperation(operationId)
      .then((value) => {
        if (active) setResult({ id: operationId, value })
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
    return () => {
      active = false
    }
  }, [isOpen, operationId])
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Отмена операции">
      {error && <p role="alert">{error}</p>}
      {result?.id === operationId ? (
        <Link to={`/review/${result.value.proposal_id}`}>Проверить последствия отмены</Link>
      ) : (
        <p>Подготовка предпросмотра…</p>
      )}
    </Modal>
  )
}
