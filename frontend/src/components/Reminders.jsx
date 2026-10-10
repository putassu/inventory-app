import { randomId } from '../utils/id'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, write } from '../api/client'
import { Help } from './ui/Help'

const categories = { medicine: 'Лекарства', food: 'Продукты', document: 'Документы' }
const initialValues = {
  categories: ['medicine', 'food', 'document'],
  location_ids: [],
  offsets_before_expiry: [30, 7, 1],
  local_delivery_time: '09:00',
  timezone: 'Europe/Moscow',
  quiet_hours: ['22:00', '08:00'],
  send_expired: true,
  repeat_expired_interval: 7,
  repeat_expired_max_count: 0,
  group_mode: 'by_day',
  channels: ['in_app'],
  include_archived: false,
  hide_sensitive_details_on_lock_screen: true,
}

function RuleForm({ rule, locations, onSave, onCancel }) {
  const [values, setValues] = useState(rule?.values || initialValues)
  const [offsets, setOffsets] = useState(values.offsets_before_expiry.join(', '))
  const [enabled, setEnabled] = useState(rule?.enabled ?? true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const request = useRef(null)
  const change = (name, value) => setValues((old) => ({ ...old, [name]: value }))
  return (
    <form
      className="panel"
      onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setError('')
        try {
          const raw = offsets
            .split(',')
            .map((value) => value.trim())
            .filter(Boolean)
          if (raw.some((value) => !/^\d+$/.test(value) || Number(value) > 3650) || raw.length > 12)
            throw new Error('Укажите до 12 целых чисел от 0 до 3650 через запятую.')
          if (!values.categories.length) throw new Error('Выберите хотя бы одну категорию.')
          const payload = { ...values, offsets_before_expiry: [...new Set(raw.map(Number))] }
          const body = JSON.stringify({ values: payload, enabled })
          if (request.current?.body !== body) request.current = { body, key: randomId() }
          const key = request.current.key
          if (rule)
            await write(
              '/reminder-rules/' + rule.id,
              { expected_version: rule.version, enabled, values: payload },
              'PATCH',
              key,
            )
          else await write('/reminder-rules', payload, 'POST', key)
          await onSave()
        } catch (e) {
          setError(e.message)
        } finally {
          setBusy(false)
        }
      }}
    >
      <h3>{rule ? 'Изменить правило' : 'Новое правило'}</h3>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <fieldset disabled={busy}>
        <legend>
          Категории{' '}
          <Help title="Категории напоминаний">
            Правило проверяет сроки только выбранных категорий. Поддерживаются лекарства, продукты и
            документы. Неизвестный срок не превращается в выдуманную дату; сначала уточните его в
            карточке.
          </Help>
        </legend>
        {Object.entries(categories).map(([code, label]) => (
          <label className="check" key={code}>
            <input
              type="checkbox"
              checked={values.categories.includes(code)}
              onChange={(e) =>
                change(
                  'categories',
                  e.target.checked
                    ? [...values.categories, code]
                    : values.categories.filter((c) => c !== code),
                )
              }
            />
            {label}
          </label>
        ))}
      </fieldset>
      <label>
        Места{' '}
        <Help title="Места напоминаний">
          Ограничивает правило выбранными местами хранения. Пустой список означает все места. Здесь
          выбираются конкретные места по их идентификаторам; включение родителя не следует считать
          автоматическим выбором всех вложенных секций.
        </Help>
        <select
          multiple
          aria-label="Места"
          disabled={busy}
          value={values.location_ids}
          onChange={(e) =>
            change(
              'location_ids',
              [...e.target.selectedOptions].map((o) => o.value),
            )
          }
        >
          {locations.map((location) => (
            <option key={location.id} value={location.id}>
              {location.full_path}
            </option>
          ))}
        </select>
        <small>Ничего не выбрано — все места.</small>
      </label>
      <label>
        За сколько дней до срока{' '}
        <Help title="Дни до срока">
          До 12 целых чисел от 0 до 3650 через запятую, например 30, 7, 1. Ноль — день окончания
          срока. Повторяющиеся значения объединяются. Уведомления рассчитываются относительно
          действующего срока, включая срок после открытия.
        </Help>
        <input
          disabled={busy}
          value={offsets}
          aria-label="За сколько дней до срока"
          onChange={(e) => setOffsets(e.target.value)}
          placeholder="30, 7, 1"
        />
        <small>Целые дни через запятую; 0 — день окончания срока.</small>
      </label>
      <div className="form-grid">
        <label>
          Время уведомления{' '}
          <Help title="Время уведомления">
            Локальное время отправки по часовому поясу этого правила. Если оно попадает в тихие
            часы, доставка откладывается до их окончания. Уведомления создаются планировщиком,
            поэтому он должен работать.
          </Help>
          <input
            disabled={busy}
            required
            type="time"
            value={values.local_delivery_time}
            aria-label="Время уведомления"
            onChange={(e) => change('local_delivery_time', e.target.value)}
          />
        </label>
        <label>
          Часовой пояс{' '}
          <Help title="Часовой пояс правила">
            Зона IANA, например Europe/Moscow. Сохраняется в самом правиле независимо от часового
            пояса профиля и определяет календарные даты, время доставки и тихие часы.
          </Help>
          <input
            disabled={busy}
            required
            value={values.timezone}
            aria-label="Часовой пояс"
            onChange={(e) => change('timezone', e.target.value)}
            placeholder="Europe/Moscow"
          />
        </label>
      </div>
      <label className="check">
        <input
          disabled={busy}
          type="checkbox"
          checked={values.quiet_hours.length > 0}
          aria-label="Тихие часы"
          onChange={(e) => change('quiet_hours', e.target.checked ? ['22:00', '08:00'] : [])}
        />
        Тихие часы{' '}
        <Help title="Тихие часы">
          Период без доставки уведомлений, например с 22:00 до 08:00 следующего дня. Отключение
          снимает это ограничение; уведомления внутри интервала переносятся на его окончание.
        </Help>
      </label>
      {!!values.quiet_hours.length && (
        <div className="form-grid">
          <label>
            Начало тишины{' '}
            <Help title="Начало тишины">
              Начало ежедневного интервала по часовому поясу правила. Интервал может проходить через
              полночь, если конец раньше начала.
            </Help>
            <input
              disabled={busy}
              required
              type="time"
              value={values.quiet_hours[0]}
              aria-label="Начало тишины"
              onChange={(e) => change('quiet_hours', [e.target.value, values.quiet_hours[1]])}
            />
          </label>
          <label>
            Конец тишины{' '}
            <Help title="Конец тишины">
              Время возобновления доставки. Начало и конец не должны совпадать: для отключения
              интервала снимите флажок «Тихие часы».
            </Help>
            <input
              disabled={busy}
              required
              type="time"
              value={values.quiet_hours[1]}
              aria-label="Конец тишины"
              onChange={(e) => change('quiet_hours', [values.quiet_hours[0], e.target.value])}
            />
          </label>
        </div>
      )}
      <label className="check">
        <input
          disabled={busy}
          type="checkbox"
          checked={values.send_expired}
          aria-label="Сообщать об истечении срока"
          onChange={(e) => change('send_expired', e.target.checked)}
        />
        Сообщать об истечении срока{' '}
        <Help title="Сообщать об истечении срока">
          Создаёт уведомление, когда срок уже истёк. Само по себе не списывает вещь и не отправляет
          её в архив. Дополнительные повторы настраиваются ниже.
        </Help>
      </label>
      {values.send_expired && (
        <div className="form-grid">
          <label>
            Дополнительных повторов{' '}
            <Help title="Дополнительных повторов">
              Сколько раз дополнительно напоминать после первого сообщения об истечении. Ноль
              отключает дополнительные повторы; допустимо до 12. Расписание приёма лекарств эта
              функция не создаёт.
            </Help>
            <input
              disabled={busy}
              required
              type="number"
              min="0"
              max="12"
              value={values.repeat_expired_max_count}
              aria-label="Дополнительных повторов"
              onChange={(e) => change('repeat_expired_max_count', Number(e.target.value))}
            />
          </label>
          <label>
            Интервал повторов, дни{' '}
            <Help title="Интервал повторов">
              Количество календарных дней между дополнительными уведомлениями об истёкшем сроке, от
              1 до 365. Используется только при ненулевом числе повторов.
            </Help>
            <input
              disabled={busy}
              required
              type="number"
              min="1"
              max="365"
              value={values.repeat_expired_interval}
              aria-label="Интервал повторов, дни"
              onChange={(e) => change('repeat_expired_interval', Number(e.target.value))}
            />
          </label>
        </div>
      )}
      <label>
        Группировка{' '}
        <Help title="Группировка напоминаний">
          «За день» объединяет напоминания дня, «По категории» разделяет их по типам вещей, «Каждое
          отдельно» создаёт отдельные сообщения. Это влияет на ленту уведомлений, а не на учёт
          количества.
        </Help>
        <select
          disabled={busy}
          value={values.group_mode}
          aria-label="Группировка"
          onChange={(e) => change('group_mode', e.target.value)}
        >
          <option value="by_day">За день</option>
          <option value="by_category">По категории</option>
          <option value="none">Каждое отдельно</option>
        </select>
      </label>
      <label className="check">
        <input
          disabled={busy}
          type="checkbox"
          checked={values.hide_sensitive_details_on_lock_screen}
          aria-label="Скрывать чувствительные подробности"
          onChange={(e) => change('hide_sensitive_details_on_lock_screen', e.target.checked)}
        />
        Скрывать чувствительные подробности{' '}
        <Help title="Скрывать чувствительные подробности">
          Ограничивает подробности чувствительных объектов в уведомлениях этого правила. Полную
          карточку можно открыть внутри приложения. Не разрешает облачную обработку и не удаляет
          сведения из учёта.
        </Help>
      </label>
      <label className="check">
        <input
          disabled={busy}
          type="checkbox"
          checked={values.include_archived}
          aria-label="Включать архив"
          onChange={(e) => change('include_archived', e.target.checked)}
        />
        Включать архив{' '}
        <Help title="Включать архив в напоминания">
          Разрешает учитывать архивные вещи при расчёте этого правила. При выключенном флажке архив
          не участвует. Это не возвращает вещи из архива в активный каталог.
        </Help>
      </label>
      {rule && (
        <label className="check">
          <input
            disabled={busy}
            type="checkbox"
            checked={enabled}
            aria-label="Правило включено"
            onChange={(e) => setEnabled(e.target.checked)}
          />
          Правило включено{' '}
          <Help title="Правило включено">
            Включённое правило участвует в последующих расчётах планировщика. Отключение сохраняет
            его настройки, но прекращает создание новых уведомлений по нему; уже созданная история
            остаётся.
          </Help>
        </label>
      )}
      <div className="actions">
        <button disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить правило'}</button>
        <button className="quiet" type="button" disabled={busy} onClick={onCancel}>
          Отмена
        </button>
      </div>
    </form>
  )
}

const loadData = () => Promise.all([api('/reminder-rules'), api('/locations')])

export default function Reminders() {
  const [rules, setRules] = useState([])
  const [cursor, setCursor] = useState(null)
  const [locations, setLocations] = useState([])
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const update = useCallback(([current, places]) => {
    setRules(current.items)
    setCursor(current.next_cursor)
    setLocations(places.items)
  }, [])
  const load = async () => update(await loadData())
  useEffect(() => {
    loadData()
      .then(update)
      .catch((e) => setError(e.message))
  }, [update])
  return (
    <section aria-label="Правила напоминаний">
      <div className="heading">
        <h2>Напоминания о сроках</h2>
        <button disabled={!!editing} onClick={() => setEditing({})}>
          Новое правило
        </button>
      </div>
      <p>
        Уведомления появляются в приложении по срокам лекарств, продуктов и документов, включая срок
        после открытия.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {editing && (
        <RuleForm
          key={editing.id || 'new'}
          rule={editing.id ? editing : null}
          locations={locations}
          onSave={async () => {
            await load()
            setEditing(null)
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {rules.map((rule) => (
        <article className="card" key={rule.id}>
          <div className="row">
            <strong>{rule.values.categories.map((c) => categories[c]).join(', ')}</strong>
            <span>{rule.enabled ? 'Включено' : 'Выключено'}</span>
          </div>
          <p>
            За {rule.values.offsets_before_expiry.join(', ') || '—'} дн. до срока ·{' '}
            {rule.values.local_delivery_time}, {rule.values.timezone}
          </p>
          <div className="actions">
            <button
              className="secondary"
              disabled={busy || !!editing}
              onClick={() => setEditing(rule)}
            >
              Изменить правило
            </button>
            {rule.enabled && (
              <button
                className="quiet"
                disabled={busy || !!editing}
                onClick={async () => {
                  setBusy(true)
                  setError('')
                  try {
                    await api(`/reminder-rules/${rule.id}?expected_version=${rule.version}`, {
                      method: 'DELETE',
                    })
                    await load()
                  } catch (e) {
                    setError(e.message)
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                Отключить правило
              </button>
            )}
          </div>
        </article>
      ))}
      {!rules.length && !editing && (
        <p className="muted">Создайте правило, чтобы получать напоминания о сроках.</p>
      )}
      {cursor && (
        <button
          className="secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            setError('')
            try {
              const more = await api('/reminder-rules?cursor=' + encodeURIComponent(cursor))
              setRules((old) => [...old, ...more.items])
              setCursor(more.next_cursor)
            } catch (e) {
              setError(e.message)
            } finally {
              setBusy(false)
            }
          }}
        >
          Ещё правила
        </button>
      )}
    </section>
  )
}
