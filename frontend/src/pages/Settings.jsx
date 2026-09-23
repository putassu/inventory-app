import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { SettingsPanel } from '../components/SettingsPanel'
import Reminders from '../components/Reminders'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { write } from '../api/client'
export function Settings() {
  const { user, logout, workspaces, activeWorkspace, selectWorkspace } = useAuth()
  const { theme, setTheme } = useTheme()
  const [tab, setTab] = useState('profile')
  const [profile, setProfile] = useState(user)
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
          rules: 'Правила сроков',
        }).map(([key, text]) => (
          <Button
            key={key}
            variant={key === tab ? 'primary' : 'secondary'}
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
          <Select label="Тема" value={theme} onChange={(event) => setTheme(event.target.value)}>
            <option value="system">Системная</option>
            <option value="light">Светлая</option>
            <option value="dark">Тёмная</option>
          </Select>
          <Input
            label="Часовой пояс IANA"
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
          />
          <Button
            onClick={async () => {
              try {
                setProfile(
                  await write('/me', { expected_version: profile.version, timezone }, 'PATCH'),
                )
                setError('')
              } catch (cause) {
                setError(cause.message)
              }
            }}
          >
            Сохранить профиль
          </Button>
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
      {tab === 'rules' && (
        <div className="legacy-panel">
          <Reminders />
        </div>
      )}
    </section>
  )
}
