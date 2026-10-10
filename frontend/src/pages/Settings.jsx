import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { SettingsPanel } from '../components/SettingsPanel'
import { ItemFieldsSettings } from '../components/ItemFieldsSettings'
import Reminders from '../components/Reminders'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { write } from '../api/client'
export function Settings() {
  const { user, logout, workspaces, activeWorkspace, selectWorkspace, updateProfile } = useAuth()
  const { theme, setTheme } = useTheme()
  const [tab, setTab] = useState('profile')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [timezone, setTimezone] = useState(user?.timezone || 'Europe/Moscow')
  const [error, setError] = useState('')
  return (
    <section className="page-stack">
      <h1>Настройки</h1>
      <nav className="toolbar" aria-label="Дополнительные разделы">
        <Link to="/tasks">Задачи</Link>
        <Link to="/history">История</Link>
        <Link to="/notifications">Уведомления</Link>
        <Link to="/data">Данные</Link>
        {user.app_role === 'admin' && <Link to="/admin">Администрирование</Link>}
      </nav>
      <div className="toolbar">
        {Object.entries({
          profile: 'Профиль',
          preferences: 'Параметры',
          fields: 'Поля вещей',
          rules: 'Правила сроков',
        }).map(([key, text]) => (
          <Button
            key={key}
            variant={key === tab ? 'primary' : 'secondary'}
            aria-pressed={key === tab}
            onClick={() => setTab(key)}
          >
            {text}
          </Button>
        ))}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {tab === 'profile' && (
        <div className="card page-stack">
          <p>
            Логин: {user.login} · {user.app_role === 'admin' ? 'Администратор' : 'Пользователь'}
          </p>
          {workspaces.length > 1 && (
            <Select
              label="Инвентарь"
              info="Рабочая область с отдельными вещами, местами и историей. Переключение меняет текущий каталог; выбор карточек и задачи из другой области сюда не переносятся."
              value={activeWorkspace?.id || ''}
              onChange={(event) =>
                selectWorkspace(workspaces.find((workspace) => workspace.id === event.target.value))
              }
            >
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </Select>
          )}
          <Select
            label="Тема"
            info="Светлая, тёмная или автоматически по настройке устройства. Меняется сразу в этом браузере и не влияет на распознавание или данные."
            value={theme}
            onChange={(event) => setTheme(event.target.value)}
          >
            <option value="system">Системная</option>
            <option value="light">Светлая</option>
            <option value="dark">Тёмная</option>
          </Select>
          <Input
            label="Часовой пояс IANA"
            info="Идентификатор зоны, например Europe/Moscow. Используется для календарных правил пользователя; в каждом правиле напоминаний есть собственный часовой пояс. IANA учитывает региональные переходы времени. Изменение сохраняется кнопкой «Сохранить профиль»."
            value={timezone}
            onChange={(event) => {
              setTimezone(event.target.value)
              setSaved(false)
            }}
          />
          <Button
            disabled={saving}
            onClick={async () => {
              if (saving) return
              setSaving(true)
              setSaved(false)
              try {
                updateProfile(
                  await write(
                    '/me',
                    { expected_version: user.version, timezone: timezone.trim() },
                    'PATCH',
                  ),
                )
                setError('')
                setSaved(true)
              } catch (cause) {
                setError(cause.message)
              } finally {
                setSaving(false)
              }
            }}
          >
            {saving ? 'Сохранение…' : 'Сохранить профиль'}
          </Button>
          {saved && <p role="status">Профиль сохранён.</p>}
          <p>Язык интерфейса: русский.</p>
          <div className="toolbar">
            <Button
              variant="secondary"
              onClick={() => logout().catch((cause) => setError(cause.message))}
            >
              Выйти
            </Button>
            <Button
              variant="secondary"
              onClick={() => logout(true).catch((cause) => setError(cause.message))}
            >
              Выйти на всех устройствах
            </Button>
          </div>
        </div>
      )}
      {tab === 'preferences' && <SettingsPanel />}
      {tab === 'fields' && <ItemFieldsSettings key={activeWorkspace?.id} />}
      {tab === 'rules' && (
        <div className="legacy-panel">
          <Reminders />
        </div>
      )}
    </section>
  )
}
