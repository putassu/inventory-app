import React, { useState, useEffect } from 'react';
import GlassCard from '../components/GlassCard';
import Button from '../components/Button';
import { apiCall } from '../api/client';
import { Activity, CheckCircle, AlertCircle, Clock, Search, ChevronDown, ChevronRight, Volume2, X } from 'lucide-react';
import ItemForm from '../components/ItemForm';
import './Tasks.css';

const Tasks = () => {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedTask, setSelectedTask] = useState(null);
  const [resolvePayload, setResolvePayload] = useState('');
  const [debugMode, setDebugMode] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);

  const fetchTasks = async () => {
    try {
      const data = await apiCall('/inventory/tasks');
      setTasks(data);
      // Update selectedTask if it exists
      if (selectedTask) {
        const updated = data.find(t => t.id === selectedTask.id);
        if (updated) {
          setSelectedTask(updated);
          let payload = updated.suggested_json || {};
          if (!payload.intent && payload.items && payload.items.length > 0) {
            const first = payload.items[0];
            payload = {
              intent: "add_item",
              item_details: {
                name: first.name,
                primary_category: first.category,
                location_id: payload.locations && payload.locations.length > 0 ? payload.locations[0] : null,
                quantity: 1,
                attributes: first.attributes || {},
                tags: first.tags || []
              }
            };
          }
          setResolvePayload(payload);
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Load debug_mode from user settings
  useEffect(() => {
    apiCall('/auth/me').then(user => {
      if (user?.settings?.developer_mode) {
        setDebugMode(true);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleResolve = async (formData) => {
    try {
      // Format the result to match VLM output format for consistency
      const finalPayload = {
        intent: 'add_item',
        item_details: { ...formData }
      };

      await apiCall(`/inventory/tasks/${selectedTask.id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ suggested_json: finalPayload })
      });
      setSelectedTask(null);
      fetchTasks();
    } catch (err) {
      alert("Error resolving task: " + err.message);
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed': return <CheckCircle className="success" size={16} />;
      case 'failed': return <AlertCircle className="danger" size={16} />;
      case 'queued':
      case 'processing': return <Activity className="primary animate-pulse" size={16} />;
      case 'user_action_required': return <Clock className="warning" size={16} />;
      default: return <Clock size={16} />;
    }
  };

  // Calculate total pipeline time
  const getTotalTime = (executionTimes) => {
    if (!executionTimes) return 0;
    return Object.values(executionTimes).reduce((a, b) => a + Number(b), 0);
  };

  const getStepColor = (step) => {
    if (step.includes('gatekeeper')) return '#f59e0b';
    if (step.includes('local_gemma')) return '#10b981';
    if (step.includes('cloud_gemma')) return '#8b5cf6';
    if (step.includes('db_writes')) return '#ef4444';
    return '#3b82f6';
  };

  return (
    <div className="tasks-page">
      <header className="page-header">
        <h1>ML Tasks & Debugger</h1>
        <p>Monitor background processing and handle HITL resolution</p>
      </header>

      <div className="tasks-layout">
        <GlassCard className="tasks-list-panel">
          <h2>Task Queue</h2>
          {loading && tasks.length === 0 ? (
            <div className="empty-state">Loading tasks...</div>
          ) : tasks.length === 0 ? (
            <div className="empty-state">No tasks found</div>
          ) : (
            <div className="tasks-list">
              {tasks.map(task => (
                <div
                  key={task.id}
                  className={`task-row ${selectedTask?.id === task.id ? 'active' : ''}`}
                  onClick={() => {
                    setSelectedTask(task);
                    let payload = task.suggested_json || {};
                    // Auto-transform gatekeeper output to VLM shape for manual resolution
                    if (!payload.intent && payload.items && payload.items.length > 0) {
                      const first = payload.items[0];
                      payload = {
                        intent: "add_item",
                        item_details: {
                          name: first.name,
                          primary_category: first.category,
                          location: payload.locations && payload.locations.length > 0 ? payload.locations[0] : null,
                          quantity: 1
                        }
                      };
                    }
                    setResolvePayload(JSON.stringify(payload, null, 2));
                  }}
                >
                  <div className="task-status-icon">{getStatusIcon(task.status)}</div>
                  <div className="task-info">
                    <div className="task-id">{task.id.slice(0, 8)}...</div>
                    <div className="task-date">{new Date(task.created_at).toLocaleString()}</div>
                  </div>
                  <div className={`task-badge ${task.status}`}>{task.status}</div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>

        <div className="task-detail-panel">
          {selectedTask ? (
            <GlassCard className="task-detail-card">
              <h2>Task Details</h2>
              <div className="detail-meta">
                <p><strong>ID:</strong> <span className="mono">{selectedTask.id}</span></p>
                <p><strong>Status:</strong> <span className={`task-badge ${selectedTask.status}`}>{selectedTask.status}</span></p>
                <p><strong>Created:</strong> {new Date(selectedTask.created_at).toLocaleString()}</p>
                <p><strong>Confidence:</strong> {selectedTask.confidence_score ?? '—'}</p>
              </div>

              {/* Input Media */}
              {selectedTask.photo_urls && selectedTask.photo_urls.length > 0 && (
                <div className="task-media">
                  <h3>Input Photos</h3>
                  <div className="media-grid">
                    {selectedTask.photo_urls.map((url, idx) => (
                      <img key={idx} src={url.replace('minio:9000', 'localhost:9010')} alt="Task input" />
                    ))}
                  </div>
                </div>
              )}

              {/* Audio */}
              {selectedTask.audio_url && (
                <div className="task-audio">
                  <h3><Volume2 size={16}/> Input Audio</h3>
                  <audio controls src={selectedTask.audio_url.replace('minio:9000', 'localhost:9010')} style={{width: '100%', height: '36px'}} />
                </div>
              )}

              {/* Transcription */}
              {selectedTask.transcription && (
                <div className="task-transcription">
                  <h3>Transcription</h3>
                  <p className="transcription-text">"{selectedTask.transcription}"</p>
                </div>
              )}

              {/* Error */}
              {selectedTask.error_message && (
                <div className="task-error">
                  <h3>Error Message</h3>
                  <div className="error-box">{selectedTask.error_message}</div>
                </div>
              )}

              {/* Pipeline Execution Times — always shown */}
              {selectedTask.execution_times && Object.keys(selectedTask.execution_times).length > 0 && (
                <div className="task-execution">
                  <h3>Pipeline Execution ({getTotalTime(selectedTask.execution_times).toFixed(1)}s total)</h3>
                  <div className="pipeline-sequence">
                    {['preprocess_and_upload', 'gatekeeper_check', 'local_gemma_extract', 'cloud_gemma_extract', 'review', 'extract_schedule', 'execute_db_writes'].map((step, idx, arr) => {
                      // Some steps might have _node suffix or not depending on logs
                      const timeStr = selectedTask.execution_times[step] || selectedTask.execution_times[`${step}_node`];
                      if (timeStr === undefined) return null; // Skipped step
                      
                      const time = Number(timeStr);
                      const pct = (time / getTotalTime(selectedTask.execution_times)) * 100;
                      
                      return (
                        <div key={step} className="pipeline-brick" style={{ width: `${Math.max(pct, 5)}%` }} title={`${step.replace(/_/g, ' ')}: ${time.toFixed(2)}s`}>
                          <div className="brick-fill" style={{ backgroundColor: getStepColor(step) }}></div>
                          <span className="brick-label">{time.toFixed(1)}s</span>
                          <span className="brick-name">{step.split('_')[0]}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Debug Logs — collapsible, only when debugMode is on */}
              {debugMode && selectedTask.debug_logs && selectedTask.debug_logs.length > 0 && (
                <div className="task-logs">
                  <h3
                    className="logs-toggle"
                    onClick={() => setLogsOpen(!logsOpen)}
                  >
                    {logsOpen ? <ChevronDown size={16}/> : <ChevronRight size={16}/>}
                    Debug Logs ({selectedTask.debug_logs.length})
                  </h3>
                  {logsOpen && (
                    <pre className="logs-box">
                      {selectedTask.debug_logs.join('\n')}
                    </pre>
                  )}
                </div>
              )}
              {selectedTask && (
          <div className="task-modal-overlay" onClick={() => setSelectedTask(null)}>
            <GlassCard className="task-modal-content" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h2>Resolving Task</h2>
                <button className="icon-btn" onClick={() => setSelectedTask(null)}>
                  <X size={20} />
                </button>
              </div>
              <div className="modal-body resolve-body">
                <div className="task-media-context">
                  {selectedTask.photo_urls && selectedTask.photo_urls.map((url, idx) => (
                     <img key={idx} src={url.replace('minio:9000', 'localhost:9010')} alt="Task Media" className="context-photo"/>
                  ))}
                  {selectedTask.transcription && (
                    <div className="context-text">
                      <strong>Transcription:</strong> {selectedTask.transcription}
                    </div>
                  )}
                </div>
                
                <div className="resolve-form-container">
                  <ItemForm 
                    initialData={resolvePayload?.item_details || {}} 
                    onSubmit={handleResolve} 
                    onCancel={() => setSelectedTask(null)}
                    submitLabel="Разрешить задачу (Resolve)"
                  />
                </div>
              </div>
            </GlassCard>
          </div>
        )}
            </GlassCard>
          ) : (
            <GlassCard className="empty-detail-card">
              <Search size={48} opacity={0.3} />
              <p>Select a task to view details</p>
            </GlassCard>
          )}
        </div>
      </div>
    </div>
  );
};

export default Tasks;
