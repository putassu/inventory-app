import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import {
  PackageSearch,
  MapPin,
  CheckSquare,
  Settings,
  LogOut,
  PlusCircle,
  Moon,
  Sun,
  ListTodo,
  Bell,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { useNotifications } from '../contexts/NotificationContext'
import { ConfirmationStatus } from './ConfirmationStatus'

const NAV_ITEMS = [
  { to: '/items', icon: PackageSearch, label: 'Вещи' },
  { to: '/locations', icon: MapPin, label: 'Места' },
  { to: '/review', icon: CheckSquare, label: 'Проверка' },
  { to: '/tasks', icon: ListTodo, label: 'Задачи' },
  { to: '/notifications', icon: Bell, label: 'Уведомления' },
  { to: '/settings', icon: Settings, label: 'Настройки' },
]

export function Layout() {
  const { user, workspaces, activeWorkspace, selectWorkspace, logout } = useAuth()
  const { theme, setTheme } = useTheme()
  const { unreadCount = 0 } = useNotifications() || {}
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = async () => {
    try {
      await logout()
    } catch {
      /* Состояние сессии обновляет AuthProvider даже при сетевой ошибке. */
    }
  }

  const toggleTheme = () => {
    const isDark = document.documentElement.classList.contains('dark')
    setTheme(isDark ? 'light' : 'dark')
  }

  return (
    <div className="layout-container">
      {/* Desktop Sidebar */}
      <aside className="sidebar">
        <div
          style={{
            padding: 'var(--space-4)',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <h1 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--brand-600)' }}>
              Инвентаризатор
            </h1>
            {user && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                {user.login}
              </div>
            )}
          </div>
          <button
            aria-label="Переключить тему"
            onClick={toggleTheme}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
            }}
          >
            {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
          </button>
        </div>

        {workspaces.length > 1 && (
          <label>
            Инвентарь
            <select
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
            </select>
          </label>
        )}
        <nav style={{ flex: 1, padding: 'var(--space-2)' }}>
          {NAV_ITEMS.filter(
            (item) => (workspaces && workspaces.length > 0) || item.to === '/settings',
          ).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-3)',
                padding: 'var(--space-3)',
                borderRadius: 'var(--radius-md)',
                color: isActive ? 'var(--brand-600)' : 'var(--text-secondary)',
                backgroundColor: isActive ? 'var(--brand-50)' : 'transparent',
                textDecoration: 'none',
                fontWeight: isActive ? 600 : 500,
                marginBottom: 'var(--space-1)',
              })}
            >
              <item.icon size={20} />
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  width: '100%',
                }}
              >
                <span>{item.label}</span>
                {item.to === '/notifications' && unreadCount > 0 && (
                  <span
                    style={{
                      background: 'var(--danger-500)',
                      color: 'white',
                      borderRadius: '10px',
                      padding: '2px 8px',
                      fontSize: '12px',
                      fontWeight: 'bold',
                    }}
                  >
                    {unreadCount}
                  </span>
                )}
              </div>
            </NavLink>
          ))}
          {user?.app_role === 'admin' && (
            <NavLink
              to="/admin"
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-3)',
                padding: 'var(--space-3)',
                borderRadius: 'var(--radius-md)',
                color: isActive ? 'var(--warning-600)' : 'var(--text-secondary)',
                backgroundColor: isActive ? 'var(--warning-50)' : 'transparent',
                textDecoration: 'none',
                fontWeight: isActive ? 600 : 500,
                marginBottom: 'var(--space-1)',
              })}
            >
              <Settings size={20} />
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  width: '100%',
                }}
              >
                <span>Администрирование</span>
              </div>
            </NavLink>
          )}
        </nav>

        <div style={{ padding: 'var(--space-3)', borderTop: '1px solid var(--border-color)' }}>
          <button
            className="btn btn-secondary"
            style={{ width: '100%', justifyContent: 'flex-start' }}
            onClick={handleLogout}
          >
            <LogOut size={18} />
            Выйти
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        {activeWorkspace && <ConfirmationStatus />}
        {(!workspaces || workspaces.length === 0) &&
        !location.pathname.startsWith('/admin') &&
        location.pathname !== '/settings' ? (
          <div style={{ padding: 'var(--space-4)' }}>
            <div className="card">
              <h2 style={{ marginBottom: 'var(--space-2)' }}>Нет доступных рабочих областей</h2>
              <p style={{ color: 'var(--text-secondary)' }}>
                Пожалуйста, обратитесь к администратору для получения доступа к рабочей области.
              </p>
            </div>
          </div>
        ) : (
          <Outlet />
        )}
      </main>

      {/* Mobile Bottom Navigation */}
      <nav className="bottom-nav glass">
        {NAV_ITEMS.slice(0, 3).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            style={({ isActive }) => ({
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '4px',
              color: isActive ? 'var(--brand-600)' : 'var(--text-secondary)',
              textDecoration: 'none',
              fontSize: '11px',
              fontWeight: 500,
            })}
          >
            <item.icon size={24} />
            {item.label}
          </NavLink>
        ))}

        {/* Floating Add Action for mobile */}
        <button
          onClick={() => navigate('/capture')}
          aria-label="Добавить фото или голос"
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--brand-600)',
            cursor: 'pointer',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '4px',
            fontSize: '11px',
            fontWeight: 500,
          }}
        >
          <PlusCircle size={32} />
        </button>

        <NavLink
          to="/settings"
          style={({ isActive }) => ({
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '4px',
            color: isActive ? 'var(--brand-600)' : 'var(--text-secondary)',
            textDecoration: 'none',
            fontSize: '11px',
            fontWeight: 500,
          })}
        >
          <Settings size={24} />
          Ещё
        </NavLink>
      </nav>
    </div>
  )
}
