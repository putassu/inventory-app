import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Eye, EyeOff } from 'lucide-react'

export function Login() {
  const [loginName, setLoginName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      await login(loginName, password)
      const target = location.state?.returnTo
      navigate(target?.startsWith('/') && !target.startsWith('//') ? target : '/items', {
        replace: true,
      })
    } catch (err) {
      setError(err.message || 'Ошибка входа')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        padding: 'var(--space-4)',
        backgroundColor: 'var(--bg-root)',
      }}
    >
      <div className="card" style={{ width: '100%', maxWidth: '400px' }}>
        <div style={{ textAlign: 'center', marginBottom: 'var(--space-6)' }}>
          <h1 style={{ fontSize: '24px', fontWeight: 700, color: 'var(--brand-600)' }}>
            Инвентаризатор
          </h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: 'var(--space-2)' }}>
            Войдите в свою учетную запись
          </p>
        </div>

        {error && (
          <div
            role="alert"
            style={{
              backgroundColor: 'var(--danger)',
              color: 'white',
              padding: 'var(--space-3)',
              borderRadius: 'var(--radius-md)',
              marginBottom: 'var(--space-4)',
              fontSize: '14px',
            }}
          >
            {error}
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}
        >
          <div>
            <label
              htmlFor="login"
              style={{
                display: 'block',
                marginBottom: 'var(--space-1)',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              Логин
            </label>
            <input
              className="input"
              id="login"
              autoComplete="username"
              type="text"
              value={loginName}
              onChange={(e) => setLoginName(e.target.value)}
              required
              disabled={loading}
              placeholder="owner"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              style={{
                display: 'block',
                marginBottom: 'var(--space-1)',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              Пароль
            </label>
            <div style={{ position: 'relative' }}>
              <input
                className="input"
                id="password"
                autoComplete="current-password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
                placeholder="••••••••"
                style={{ paddingRight: '40px' }}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                style={{
                  position: 'absolute',
                  right: '10px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading}
            style={{ marginTop: 'var(--space-2)' }}
          >
            {loading ? 'Вход...' : 'Войти'}
          </button>
        </form>
      </div>
    </div>
  )
}
