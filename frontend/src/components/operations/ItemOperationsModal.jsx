import { useRef, useState } from 'react'
import { useResource } from '../../hooks/useResource'
import { ReviewField } from '../review/ReviewField'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { useToast } from '../../contexts/ToastContext'
import { updateItem, archiveItem, restoreItem, addAlias, removeAlias } from '../../api/commands'

const CATEGORIES = [
  { code: 'medicine', name: 'Лекарства и медицина' },
  { code: 'food', name: 'Продукты питания' },
  { code: 'clothing', name: 'Одежда и обувь' },
  { code: 'equipment', name: 'Техника и инструменты' },
  { code: 'document', name: 'Документы' },
  { code: 'dishes', name: 'Посуда' },
  { code: 'cosmetics', name: 'Косметика и уход' },
  { code: 'household', name: 'Бытовые товары' },
  { code: 'hobby', name: 'Хобби и спорт' },
  { code: 'other', name: 'Другое' },
]

export function ItemOperationsModal(props) {
  return props.isOpen ? <Form {...props} /> : null
}
function Form({
  isOpen,
  onClose,
  onSuccess,
  item,
  operation = 'update', // 'update' | 'archive' | 'restore' | 'add_alias' | 'remove_alias'
  alias = null, // for remove_alias
}) {
  const { addToast } = useToast()
  const submitting = useRef(false)

  const [name, setName] = useState(item?.name || '')
  const [category, setCategory] = useState(item?.primary_category || 'other')
  const [brand, setBrand] = useState(item?.brand || '')
  const [model, setModel] = useState(item?.model || '')
  const [barcode, setBarcode] = useState(item?.barcode || '')
  const [userDescription, setUserDescription] = useState(item?.user_description || '')
  const [tagsStr, setTagsStr] = useState(item?.tags?.join(', ') || '')
  const [attributes, setAttributes] = useState(item?.attributes || {})
  const [newAlias, setNewAlias] = useState('')
  const [aliasScope, setAliasScope] = useState('workspace')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  const { data: schema } = useResource(`/forms?operation=receive_stock&category=${category}`)
  function updateAttribute(key, value) {
    const path = key.split('.').slice(1)
    setAttributes((previous) => {
      const next = structuredClone(previous)
      if (path.length === 2) next[path[0]] = { ...next[path[0]], [path[1]]: value }
      else if (value === null) delete next[path[0]]
      else next[path[0]] = value
      return next
    })
  }
  const titles = {
    update: 'Редактирование карточки вещи',
    archive: 'Архивация карточки',
    restore: 'Восстановление из архива',
    add_alias: 'Добавить синоним (Алиас)',
    remove_alias: 'Удалить синоним',
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting.current) return
    submitting.current = true
    setIsLoading(true)
    setError(null)

    try {
      const expectedVersions = item?.version ? { [`item:${item.id}`]: item.version } : {}
      if (alias?.version) expectedVersions[`alias:${alias.id}`] = alias.version
      let result

      if (operation === 'update') {
        const tags = tagsStr
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean)

        result = await updateItem(
          {
            item_id: item.id,
            name: name.trim(),
            primary_category: category,
            brand: brand.trim() || null,
            model: model.trim() || null,
            barcode: barcode.trim() || null,
            user_description: userDescription.trim() || null,
            tags,
            attributes,
          },
          expectedVersions,
        )
        addToast('Карточка успешно обновлена', 'success')
      } else if (operation === 'archive') {
        result = await archiveItem(item.id, expectedVersions)
        addToast('Вещь перенесена в архив', 'success')
      } else if (operation === 'restore') {
        result = await restoreItem(item.id, expectedVersions)
        addToast('Вещь восстановлена из архива', 'success')
      } else if (operation === 'add_alias') {
        if (!newAlias.trim()) throw new Error('Введите поисковый синоним')
        result = await addAlias(item.id, newAlias.trim(), aliasScope, expectedVersions)
        addToast('Синоним добавлен', 'success')
      } else if (operation === 'remove_alias') {
        if (!alias?.id) throw new Error('Не указан алиас для удаления')
        result = await removeAlias(alias.id, expectedVersions)
        addToast('Синоним удален', 'success')
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
      title={titles[operation] || 'Операция'}
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
            {isLoading
              ? 'Сохранение...'
              : operation === 'archive'
                ? 'Архивировать'
                : operation === 'restore'
                  ? 'Восстановить'
                  : operation === 'remove_alias'
                    ? 'Удалить'
                    : 'Сохранить'}
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

          {operation === 'update' && (
            <>
              <Input
                label="Наименование"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
              <Select
                label="Категория"
                value={category}
                onChange={(e) => {
                  setCategory(e.target.value)
                  setAttributes({})
                }}
              >
                {CATEGORIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </Select>

              <div
                style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-3)' }}
              >
                <Input label="Бренд" value={brand} onChange={(e) => setBrand(e.target.value)} />
                <Input label="Модель" value={model} onChange={(e) => setModel(e.target.value)} />
              </div>

              <Input
                label="Штрихкод / Barcode"
                value={barcode}
                onChange={(e) => setBarcode(e.target.value)}
              />

              <Input
                label="Теги (через запятую)"
                value={tagsStr}
                onChange={(e) => setTagsStr(e.target.value)}
                placeholder="зимнее, теплое, инструменты"
              />

              {schema?.fields
                .filter((field) => field.key.startsWith('attributes.'))
                .map((field) => (
                  <ReviewField
                    key={field.key}
                    field={field}
                    value={field.key
                      .split('.')
                      .slice(1)
                      .reduce((value, key) => value?.[key], attributes)}
                    onChange={(value) => updateAttribute(field.key, value)}
                  />
                ))}

              <div>
                <label
                  style={{
                    display: 'block',
                    marginBottom: 'var(--space-1)',
                    fontSize: '14px',
                    fontWeight: 500,
                  }}
                >
                  Описание
                </label>
                <textarea
                  className="input"
                  style={{ width: '100%', minHeight: '80px', resize: 'vertical' }}
                  value={userDescription}
                  onChange={(e) => setUserDescription(e.target.value)}
                  placeholder="Пользовательское примечание или описание"
                />
              </div>
            </>
          )}

          {operation === 'archive' && (
            <div style={{ fontSize: '14px', lineHeight: 1.5 }}>
              Вы действительно хотите скрыть вещь <strong>{item?.name}</strong> в архив?
              <p style={{ marginTop: 'var(--space-2)', color: 'var(--text-secondary)' }}>
                Карточка будет скрыта из основного каталога, но вся история операций сохранится. Вы
                сможете восстановить вещь в любой момент.
              </p>
            </div>
          )}

          {operation === 'restore' && (
            <div style={{ fontSize: '14px', lineHeight: 1.5 }}>
              Восстановить вещь <strong>{item?.name}</strong> из архива? Карточка снова появится в
              активном каталоге.
            </div>
          )}

          {operation === 'add_alias' && (
            <>
              <Input
                label="Поисковый синоним (Алиас)"
                value={newAlias}
                onChange={(e) => setNewAlias(e.target.value)}
                placeholder="Например, 'зеленый свитер' или 'отвертка крестовая'"
                required
              />
              <Select
                label="Область видимости"
                value={aliasScope}
                onChange={(e) => setAliasScope(e.target.value)}
              >
                <option value="workspace">Для всего инвентаря (workspace)</option>
                <option value="user">Только для меня (user)</option>
              </Select>
            </>
          )}

          {operation === 'remove_alias' && (
            <div style={{ fontSize: '14px' }}>
              Удалить синоним <strong>«{alias?.alias}»</strong> для этой вещи?
            </div>
          )}
        </fieldset>
      </form>
    </Modal>
  )
}
