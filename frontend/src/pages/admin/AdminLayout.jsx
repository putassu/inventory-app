import { Outlet, NavLink } from 'react-router-dom'
import { Settings, Cpu, HardDrive, Activity } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'

const ADMIN_TABS = [
  { to: '/admin/settings', icon: Settings, label: 'Система' },
  { to: '/admin/models', icon: Cpu, label: 'Модели' },
  { to: '/admin/queues', icon: Activity, label: 'Очереди и GPU' },
  { to: '/admin/maintenance', icon: HardDrive, label: 'Обслуживание' },
]

export function AdminLayout() {
  const { user } = useAuth()

  if (user?.app_role !== 'admin')
    return <p role="alert">Этот раздел доступен только администратору.</p>

  return (
    <div
      className="page-container"
      style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
    >
      <header className="page-header" style={{ paddingBottom: 0 }}>
        <h1 style={{ marginBottom: 'var(--space-4)' }}>Администрирование</h1>
        <div
          style={{
            display: 'flex',
            gap: 'var(--space-4)',
            borderBottom: '1px solid var(--border-color)',
            overflowX: 'auto',
          }}
        >
          {ADMIN_TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: 'var(--space-3)',
                color: isActive ? 'var(--brand-600)' : 'var(--text-secondary)',
                borderBottom: isActive ? '2px solid var(--brand-600)' : '2px solid transparent',
                textDecoration: 'none',
                fontWeight: isActive ? 600 : 500,
                whiteSpace: 'nowrap',
              })}
            >
              <tab.icon size={16} />
              {tab.label}
            </NavLink>
          ))}
        </div>
      </header>
      <div style={{ flex: 1, overflowY: 'auto', padding: 'var(--space-4) 0' }}>
        <Outlet />
      </div>
    </div>
  )
}
