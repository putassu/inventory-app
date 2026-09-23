import { useRef, useState } from 'react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { useToast } from '../../contexts/ToastContext'
import { createLocation, updateLocation, moveLocation, archiveLocation } from '../../api/commands'
import { descendants, isSystemLocation } from '../../utils/locations'

export function LocationOperationsModal(props) {
  return props.isOpen ? <Form {...props} /> : null
}
function Form({
  isOpen,
  onClose,
  onSuccess,
  location = null,
  locations = [],
  operation = 'create', // 'create' | 'update' | 'move' | 'archive'
}) {
  const { addToast } = useToast()
  const submitting = useRef(false)

  const [name, setName] = useState(location?.name || '')
  const [kind, setKind] = useState(location?.kind || 'place')
  const [parentId, setParentId] = useState(location?.parent_id || '')
  const [description, setDescription] = useState(location?.description || '')
  const [transferToId, setTransferToId] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  const parentLocation = parentId ? locations.find((l) => l.id === parentId) : null
  const excluded = location?.id ? descendants(locations, location.id) : new Set()
  const titles = {
    create: parentLocation
      ? `Новый потомок в «${parentLocation.name}»`
      : 'Новое место или контейнер',
    update: 'Редактирование места',
    move: 'Перемещение места / контейнера',
    archive: 'Архивация места',
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting.current) return
    submitting.current = true
    setIsLoading(true)
    setError(null)

    try {
      const expectedVersions = location?.version
        ? { [`location:${location.id}`]: location.version }
        : {}
      let result

      if (operation === 'create') {
        if (!name.trim()) throw new Error('Укажите название места')
        result = await createLocation(
          {
            name: name.trim(),
            kind,
            parent_id: parentId || null,
            description: description.trim() || null,
          },
          expectedVersions,
        )
        addToast('Место успешно создано', 'success')
      } else if (operation === 'update') {
        if (!name.trim()) throw new Error('Укажите название места')
        result = await updateLocation(
          {
            location_id: location.id,
            name: name.trim(),
            description: description.trim() || null,
          },
          expectedVersions,
        )
        addToast('Место успешно обновлено', 'success')
      } else if (operation === 'move') {
        result = await moveLocation(
          {
            location_id: location.id,
            parent_id: parentId || null,
          },
          expectedVersions,
        )
        addToast('Место успешно перемещено', 'success')
      } else if (operation === 'archive') {
        result = await archiveLocation(location.id, transferToId || null, expectedVersions)
        addToast('Место отправлено в архив', 'success')
      }

      if (onSuccess) onSuccess(result)
      onClose()
    } catch (err) {
      setError(err.message || 'Ошибка выполнения действия')
    } finally {
      submitting.current = false
      setIsLoading(false)
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      busy={isLoading}
      onClose={onClose}
      title={titles[operation] || 'Место хранения'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isLoading}>
            Отмена
          </Button>
          <Button
            variant={operation === 'archive' ? 'danger' : 'primary'}
            onClick={handleSubmit}
            disabled={isLoading}
          >
            {isLoading ? 'Сохранение...' : operation === 'archive' ? 'Архивировать' : 'Сохранить'}
          </Button>
        </>
      }
    >
      <form
        onSubmit={handleSubmit}
        style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}
      >
        <fieldset disabled={isLoading} className="page-stack">
          {error && (
            <div
              style={{
                padding: 'var(--space-3)',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid var(--danger)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--danger)',
                fontSize: '14px',
              }}
            >
              {error}
            </div>
          )}

          {(operation === 'create' || operation === 'update') && (
            <>
              <Input
                label="Название"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Например, Полка 2 или Коробка с проводами"
                required
              />

              {operation === 'create' && (
                <Select label="Тип" value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="place">Стационарное место (шкаф, комната, полка)</option>
                  <option value="container">
                    Переносимый контейнер (коробка, сумка, органайзер)
                  </option>
                </Select>
              )}

              <div>
                <label
                  style={{
                    display: 'block',
                    marginBottom: 'var(--space-1)',
                    fontSize: '14px',
                    fontWeight: 500,
                  }}
                >
                  Описание / Заметки
                </label>
                <textarea
                  className="input"
                  style={{ width: '100%', minHeight: '60px', resize: 'vertical' }}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Ориентир или примечание"
                />
              </div>
            </>
          )}

          {(operation === 'create' || operation === 'move') && (
            <Select
              label="Родительское место (Внутри чего находится)"
              value={parentId}
              onChange={(e) => setParentId(e.target.value)}
            >
              <option value="">-- Верхний уровень (без родителя) --</option>
              {locations
                .filter((l) => !excluded.has(l.id) && !isSystemLocation(l))
                .map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.full_path || l.name}
                  </option>
                ))}
            </Select>
          )}

          {operation === 'archive' && (
            <>
              <div style={{ fontSize: '14px', lineHeight: 1.5 }}>
                Вы действительно хотите отправить в архив место <strong>{location?.name}</strong>?
              </div>
              <Select
                label="Куда перенести содержимое (если есть вещи)"
                value={transferToId}
                onChange={(e) => setTransferToId(e.target.value)}
              >
                <option value="">-- Оставить без указанного места --</option>
                {locations
                  .filter((l) => !excluded.has(l.id))
                  .map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.full_path || l.name}
                    </option>
                  ))}
              </Select>
            </>
          )}
        </fieldset>
      </form>
    </Modal>
  )
}
