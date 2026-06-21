import React, { useState, useEffect } from 'react';
import GlassCard from '../components/GlassCard';
import Input from '../components/Input';
import Button from '../components/Button';
import { apiCall } from '../api/client';
import { Settings as SettingsIcon, Save, RefreshCw, User, Server } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import './Settings.css';

const UserSettingsForm = () => {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchSettings = async () => {
    try {
      const data = await apiCall('/auth/me/settings');
      setSettings(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleChange = (key, value) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiCall('/auth/me/settings', {
        method: 'PUT',
        body: JSON.stringify(settings)
      });
      alert('Preferences saved successfully!');
    } catch (err) {
      alert("Failed to save preferences: " + err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="empty-state">Loading preferences...</div>;
  if (!settings) return null;

  return (
    <div className="user-settings-form">
      <div className="setting-group">
        <h3>Audit & Retention</h3>
        <label>
          Remind to confirm item location every (days):
          <Input 
            type="number" 
            value={settings.audit_reminder_days} 
            onChange={(e) => handleChange('audit_reminder_days', parseInt(e.target.value))}
          />
        </label>
        <label>
          Only audit items with more than N moves:
          <Input 
            type="number" 
            value={settings.audit_min_moves} 
            onChange={(e) => handleChange('audit_min_moves', parseInt(e.target.value))}
          />
        </label>
        <label className="checkbox-label">
          <input 
            type="checkbox" 
            checked={settings.auto_archive_depleted} 
            onChange={(e) => handleChange('auto_archive_depleted', e.target.checked)}
          />
          Automatically archive items when quantity reaches 0
        </label>
      </div>

      <div className="setting-group">
        <h3>System & AI Preferences</h3>
        <label className="checkbox-label">
          <input 
            type="checkbox" 
            checked={settings.local_llm_only} 
            onChange={(e) => handleChange('local_llm_only', e.target.checked)}
          />
          Disable Cloud Models (Force Local LLM)
        </label>
        <label className="checkbox-label">
          <input 
            type="checkbox" 
            checked={settings.developer_mode} 
            onChange={(e) => handleChange('developer_mode', e.target.checked)}
          />
          Developer Mode (Show raw error text & logs)
        </label>
        <label className="checkbox-label">
          <input 
            type="checkbox" 
            checked={settings.compact_view} 
            onChange={(e) => handleChange('compact_view', e.target.checked)}
          />
          Use compact UI lists
        </label>
      </div>

      <div className="setting-actions">
        <Button onClick={handleSave} disabled={saving}>
          <Save size={16} /> {saving ? "Saving..." : "Save Preferences"}
        </Button>
      </div>
    </div>
  );
};

const AdminSettings = () => {
  const [settingsList, setSettingsList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingKey, setEditingKey] = useState(null);
  const [editValue, setEditValue] = useState('');

  const fetchSettings = async () => {
    try {
      const data = await apiCall('/admin/settings');
      setSettingsList(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleSave = async (key) => {
    try {
      await apiCall(`/admin/settings/${key}`, {
        method: 'PUT',
        body: JSON.stringify({ value: editValue })
      });
      setEditingKey(null);
      fetchSettings();
    } catch (err) {
      alert("Failed to save setting: " + err.message);
    }
  };

  return (
    <div className="admin-settings">
      <div className="settings-header">
        <h2><Server size={20} /> Dynamic Variables</h2>
        <Button onClick={fetchSettings} variant="secondary"><RefreshCw size={16} /> Refresh</Button>
      </div>

      {loading ? (
        <div className="empty-state">Loading settings...</div>
      ) : settingsList.length === 0 ? (
        <div className="empty-state">No dynamic overrides active. System is using defaults.</div>
      ) : (
        <div className="settings-list">
          {settingsList.map(setting => (
            <div key={setting.key} className="setting-row">
              <div className="setting-info">
                <h3>{setting.key}</h3>
                <p>{setting.description}</p>
              </div>
              <div className="setting-value">
                {editingKey === setting.key ? (
                  <div className="setting-edit-group">
                    <Input 
                      value={editValue} 
                      onChange={(e) => setEditValue(e.target.value)}
                    />
                    <Button onClick={() => handleSave(setting.key)}><Save size={16} /> Save</Button>
                    <Button variant="secondary" onClick={() => setEditingKey(null)}>Cancel</Button>
                  </div>
                ) : (
                  <div className="setting-display-group">
                    <code>{JSON.stringify(setting.value)}</code>
                    <Button variant="secondary" onClick={() => {
                      setEditingKey(setting.key);
                      setEditValue(JSON.stringify(setting.value));
                    }}>Edit</Button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const Settings = () => {
  const { user } = useAuth();
  // If user is admin (tier ADMIN or similar), default to 'admin' tab, else 'user'
  const isAdmin = user?.email === 'admin@example.com' || user?.tier === 'ADMIN';
  const [activeTab, setActiveTab] = useState('user');

  return (
    <div className="settings-page">
      <header className="page-header">
        <h1>Settings</h1>
        <p>Manage your account and application preferences</p>
      </header>

      <div className="settings-tabs">
        <button 
          className={`tab-btn ${activeTab === 'user' ? 'active' : ''}`}
          onClick={() => setActiveTab('user')}
        >
          <User size={16} /> My Preferences
        </button>
        {isAdmin && (
          <button 
            className={`tab-btn ${activeTab === 'admin' ? 'active' : ''}`}
            onClick={() => setActiveTab('admin')}
          >
            <SettingsIcon size={16} /> Global Admin Settings
          </button>
        )}
      </div>

      <GlassCard className="settings-card mt-20">
        {activeTab === 'user' ? <UserSettingsForm /> : <AdminSettings />}
      </GlassCard>
    </div>
  );
};

export default Settings;
