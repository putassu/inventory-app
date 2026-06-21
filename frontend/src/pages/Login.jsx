import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Eye, EyeOff } from 'lucide-react';
import GlassCard from '../components/GlassCard';
import Input from '../components/Input';
import Button from '../components/Button';
import './Login.css';

const Login = () => {
  const [username, setUsername] = useState('admin@example.com');
  const [password, setPassword] = useState('admin123456');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await login(username, password);
      navigate('/');
    } catch (err) {
      setError(err.message || 'Login failed');
    }
  };

  return (
    <div className="login-container">
      <div className="login-bg-elements">
        <div className="orb orb-1"></div>
        <div className="orb orb-2"></div>
      </div>
      
      <GlassCard className="login-card animate-fade-in">
        <div className="login-header">
          <h1>AI Inventory</h1>
          <p>Sign in to access the admin dashboard</p>
        </div>

        {error && <div className="error-alert">{error}</div>}

        <form onSubmit={handleSubmit} className="login-form">
          <Input 
            label="Email Address" 
            type="email" 
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <div className="password-input-wrapper" style={{ position: 'relative' }}>
            <Input 
              label="Password" 
              type={showPassword ? "text" : "password"} 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button 
              type="button" 
              className="password-toggle-btn"
              onClick={() => setShowPassword(!showPassword)}
              style={{
                position: 'absolute',
                right: '12px',
                top: '32px',
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer'
              }}
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          <Button type="submit" className="login-submit-btn">
            Access System
          </Button>
        </form>
      </GlassCard>
    </div>
  );
};

export default Login;
