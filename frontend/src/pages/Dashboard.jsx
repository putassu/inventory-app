import React, { useEffect, useState } from 'react';
import GlassCard from '../components/GlassCard';
import { apiCall } from '../api/client';
import { Activity, Server, Database, Package, CheckCircle, AlertCircle, Clock, MapPin } from 'lucide-react';
import './Dashboard.css';

const Dashboard = () => {
  const [health, setHealth] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [items, setItems] = useState([]);
  const [locations, setLocations] = useState([]);

  useEffect(() => {
    apiCall('/health').then(setHealth).catch(console.error);
    apiCall('/inventory/tasks').then(data => setTasks(data.slice(0, 10))).catch(console.error);
    apiCall('/inventory/items?include_archived=false').then(data => setItems(data.slice(0, 5))).catch(console.error);
    apiCall('/inventory/locations').then(data => {
      // Flatten tree for count
      const flat = [];
      const walk = (nodes) => { nodes.forEach(n => { flat.push(n); if (n.children) walk(n.children); }); };
      walk(data);
      setLocations(flat);
    }).catch(console.error);
  }, []);

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed': return <CheckCircle className="success" size={14} />;
      case 'failed': return <AlertCircle className="danger" size={14} />;
      case 'processing':
      case 'queued': return <Activity className="primary animate-pulse" size={14} />;
      case 'user_action_required': return <Clock className="warning" size={14} />;
      default: return <Clock size={14} />;
    }
  };

  return (
    <div className="dashboard-page">
      <header className="page-header">
        <h1>Dashboard Overview</h1>
        <p>System status, metrics, and recent activity</p>
      </header>

      <div className="metrics-grid">
        <GlassCard className="metric-card" hoverEffect>
          <div className="metric-icon primary"><Activity /></div>
          <div className="metric-content">
            <h3>API Status</h3>
            <p className={health?.status === 'ok' ? 'status-ok' : 'status-err'}>
              {health ? 'Online' : 'Checking...'}
            </p>
          </div>
        </GlassCard>

        <GlassCard className="metric-card" hoverEffect>
          <div className="metric-icon accent"><Package /></div>
          <div className="metric-content">
            <h3>Items</h3>
            <p>{items.length}+ tracked</p>
          </div>
        </GlassCard>

        <GlassCard className="metric-card" hoverEffect>
          <div className="metric-icon success"><MapPin /></div>
          <div className="metric-content">
            <h3>Locations</h3>
            <p>{locations.length} total</p>
          </div>
        </GlassCard>

        <GlassCard className="metric-card" hoverEffect>
          <div className="metric-icon warning"><Server /></div>
          <div className="metric-content">
            <h3>Tasks</h3>
            <p>{tasks.filter(t => t.status === 'processing' || t.status === 'queued').length} active</p>
          </div>
        </GlassCard>
      </div>

      <div className="dashboard-content">
        <GlassCard className="panel-card">
          <h2>Recent Activity</h2>
          {tasks.length === 0 ? (
            <div className="empty-state">No recent activity detected.</div>
          ) : (
            <div className="activity-list">
              {tasks.map(task => (
                <div key={task.id} className={`activity-row ${task.status}`}>
                  <div className="activity-icon">{getStatusIcon(task.status)}</div>
                  <div className="activity-info">
                    <div className="activity-title">
                      Task <span className="mono">{task.id.slice(0, 8)}...</span>
                    </div>
                    <div className="activity-meta">
                      <span className={`task-badge ${task.status}`}>{task.status}</span>
                      <span className="activity-time">{new Date(task.updated_at).toLocaleString()}</span>
                    </div>
                  </div>
                  {task.execution_times && Object.keys(task.execution_times).length > 0 && (
                    <div className="activity-timing">
                      {Object.values(task.execution_times).reduce((a, b) => a + Number(b), 0).toFixed(1)}s total
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        <GlassCard className="panel-card">
          <h2>Recent Items</h2>
          {items.length === 0 ? (
            <div className="empty-state">No items yet.</div>
          ) : (
            <div className="activity-list">
              {items.map(item => (
                <div key={item.id} className="activity-row">
                  <div className="activity-icon">
                    <span className={`status-dot ${item.status === 'completed' ? 'green' : item.status === 'failed' || item.status === 'user_action_required' ? 'red' : 'yellow'}`}></span>
                  </div>
                  <div className="activity-info">
                    <div className="activity-title">{item.name || 'Processing...'}</div>
                    <div className="activity-meta">
                      <span className="badge category">{item.primary_category}</span>
                      <span className="activity-time">{new Date(item.updated_at).toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      </div>
    </div>
  );
};

export default Dashboard;
