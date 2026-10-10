import { useState } from 'react'
import { useResource } from '../hooks/useResource'
import { useToast } from '../contexts/ToastContext'
import { write } from '../api/client'
import { randomId } from '../utils/id'
import { Button } from './ui/Button'
import { Input } from './ui/Input'
import { Select } from './ui/Select'
import { Help } from './ui/Help'

export function ItemFieldsSettings() {
  const resource = useResource('/item-fields')
  const categories = useResource('/reference/categories')
  if (!resource.data) return <p role="status">{resource.error?.message || 'Загрузка полей…'}</p>
  return (
    <Editor
      key={resource.data.version}
      initial={resource.data}
      categories={categories.data?.items || []}
      reload={resource.reload}
    />
  )
}

function Editor({ initial, categories, reload }) {
  const { addToast } = useToast()
  const [hidden, setHidden] = useState(initial.hidden_fields)
  const [fields, setFields] = useState(initial.custom_fields)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const update = (key, patch) => {
    setSaved(false)
    setFields((previous) =>
      previous.map((field) => (field.key === key ? { ...field, ...patch } : field)),
    )
  }
  return (
    <form
      className="card page-stack"
      onSubmit={async (event) => {
        event.preventDefault()
        if (busy) return
        setBusy(true)
        setError('')
        setSaved(false)
        try {
          await write(
            '/item-fields',
            { expected_version: initial.version, hidden_fields: hidden, custom_fields: fields },
            'PATCH',
          )
          setSaved(true)
          addToast('Настройки полей сохранены', 'success')
          reload()
        } catch (cause) {
          setError(cause.message)
        } finally {
          setBusy(false)
        }
      }}
    >
      <h2>Поля карточки вещи</h2>
      <p>
        Общие для текущего инвентаря. Скрываются только пустые поля; заполненные значения остаются
        видимыми и доступными для исправления.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}{' '}
          <Button variant="text" onClick={reload}>
            Загрузить настройки заново
          </Button>
        </p>
      )}
      {saved && <p role="status">Настройки полей сохранены.</p>}
      <fieldset disabled={busy} className="page-stack">
        <details>
          <summary>Стандартные необязательные поля</summary>
          <div className="form-grid">
            {initial.builtin_fields.map((field) => (
              <label className="check" key={field.key}>
                <input
                  type="checkbox"
                  checked={!hidden.includes(field.key)}
                  onChange={(event) => {
                    setSaved(false)
                    setHidden((previous) =>
                      event.target.checked
                        ? previous.filter((key) => key !== field.key)
                        : [...previous, field.key],
                    )
                  }}
                />
                {field.label}
                <Help title={field.label}>
                  Показывать пустое поле при создании и редактировании. Отключение не стирает ранее
                  сохранённые данные и не меняет работу сроков или поиска.
                </Help>
              </label>
            ))}
          </div>
        </details>
        <h3>Пользовательские атрибуты</h3>
        {!fields.length && <p>Например, добавьте «На продажу» с типом «Да / нет».</p>}
        {fields.map((field) => (
          <fieldset className="card page-stack" key={field.key}>
            <legend>{field.label || 'Новое свойство'}</legend>
            <Input
              label="Название свойства"
              required
              maxLength={80}
              value={field.label}
              onChange={(event) => update(field.key, { label: event.target.value })}
              info="Название показывается в форме и описании вещи. Его можно изменить без потери значений."
            />
            <Select
              label="Тип значения"
              value={field.type}
              disabled={initial.custom_fields.some((old) => old.key === field.key)}
              onChange={(event) => update(field.key, { type: event.target.value })}
              info="После сохранения тип фиксируется, чтобы существующие значения оставались корректными. Для другого типа добавьте новое свойство."
            >
              <option value="boolean">Да / нет</option>
              <option value="string">Текст</option>
              <option value="decimal">Число</option>
              <option value="date">Дата</option>
            </Select>
            <label className="check">
              <input
                type="checkbox"
                checked={field.enabled}
                onChange={(event) => update(field.key, { enabled: event.target.checked })}
              />
              Показывать поле
              <Help title="Показывать поле">
                Отключите ненужное свойство. Записанные значения сохраняются; свойство можно
                включить снова.
              </Help>
            </label>
            <details>
              <summary>
                Категории: {field.categories.length ? field.categories.length : 'все'}
              </summary>
              <p>Если ничего не выбрано, свойство доступно всем категориям.</p>
              <div className="form-grid">
                {categories.map((category) => (
                  <label className="check" key={category.code}>
                    <input
                      type="checkbox"
                      checked={field.categories.includes(category.code)}
                      onChange={(event) =>
                        update(field.key, {
                          categories: event.target.checked
                            ? [...field.categories, category.code]
                            : field.categories.filter((code) => code !== category.code),
                        })
                      }
                    />
                    {category.name}
                  </label>
                ))}
              </div>
            </details>
            {!initial.custom_fields.some((old) => old.key === field.key) && (
              <Button
                variant="text"
                onClick={() => setFields(fields.filter((row) => row.key !== field.key))}
              >
                Убрать новое поле
              </Button>
            )}
          </fieldset>
        ))}
        <Button
          variant="secondary"
          disabled={fields.length >= 50}
          onClick={() => {
            setSaved(false)
            setFields([
              ...fields,
              {
                key: 'f_' + randomId().replaceAll('-', ''),
                label: '',
                type: 'boolean',
                enabled: true,
                categories: [],
              },
            ])
          }}
        >
          Добавить свойство
        </Button>
        <Button type="submit">{busy ? 'Сохраняем…' : 'Сохранить поля'}</Button>
      </fieldset>
    </form>
  )
}
