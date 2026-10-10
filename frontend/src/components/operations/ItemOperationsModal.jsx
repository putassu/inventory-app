import { useRef, useState } from 'react'
import { archiveItem, restoreItem, addAlias, removeAlias } from '../../api/commands'
import { useToast } from '../../contexts/ToastContext'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { EditItemModal } from './EditItemModal'

const titles = {
  archive: 'Архивация карточки',
  restore: 'Восстановление из архива',
  add_alias: 'Добавить синоним',
  remove_alias: 'Удалить синоним',
}

export function ItemOperationsModal(props) {
  if (!props.isOpen) return null
  return !props.operation || props.operation === 'update' ? (
    <EditItemModal {...props} />
  ) : (
    <Form {...props} />
  )
}

function Form({ item, operation, alias, onClose, onSuccess }) {
  const [name, setName] = useState(''),
    [scope, setScope] = useState('workspace')
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  const submitting = useRef(false)
  const { addToast } = useToast()
  const caption = {
    archive: 'Архивировать',
    restore: 'Восстановить',
    add_alias: 'Сохранить',
    remove_alias: 'Удалить',
  }[operation]
  return (
    <Modal isOpen busy={busy} onClose={onClose} title={titles[operation]}>
      <form
        className="page-stack"
        onSubmit={async (event) => {
          event.preventDefault()
          if (submitting.current) return
          submitting.current = true
          setBusy(true)
          setError('')
          try {
            const versions = { [`item:${item.id}`]: item.version }
            if (alias?.version) versions[`alias:${alias.id}`] = alias.version
            let result
            if (operation === 'archive') result = await archiveItem(item.id, versions)
            else if (operation === 'restore') result = await restoreItem(item.id, versions)
            else if (operation === 'add_alias') {
              if (!name.trim()) throw new Error('Введите поисковый синоним.')
              result = await addAlias(item.id, name.trim(), scope, versions)
            } else result = await removeAlias(alias.id, versions)
            addToast('Изменения сохранены', 'success')
            onSuccess?.(result)
            onClose()
          } catch (cause) {
            if (cause.pending) onClose()
            else setError(cause.message)
          } finally {
            submitting.current = false
            setBusy(false)
          }
        }}
      >
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <fieldset disabled={busy} className="page-stack">
          {operation === 'archive' && (
            <>
              <p>
                Вы действительно хотите скрыть вещь <strong>{item.name}</strong> в архив?
              </p>
              <p>История сохранится. Вещь можно восстановить в любой момент.</p>
            </>
          )}
          {operation === 'restore' && (
            <p>
              Восстановить вещь <strong>{item.name}</strong> из архива?
            </p>
          )}
          {operation === 'remove_alias' && (
            <p>
              Удалить синоним <strong>«{alias?.alias}»</strong>?
            </p>
          )}
          {operation === 'add_alias' && (
            <>
              <Input
                label="Поисковый синоним"
                required
                maxLength={255}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              <Select
                label="Область видимости"
                value={scope}
                onChange={(event) => setScope(event.target.value)}
              >
                <option value="workspace">Для всего инвентаря</option>
                <option value="user">Только для меня</option>
              </Select>
            </>
          )}
          <div className="actions">
            <Button variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" variant={operation === 'archive' ? 'danger' : 'primary'}>
              {busy ? 'Сохраняем…' : caption}
            </Button>
          </div>
        </fieldset>
      </form>
    </Modal>
  )
}
