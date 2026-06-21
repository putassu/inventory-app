import React, { useState, useEffect } from 'react';
import GlassCard from '../components/GlassCard';
import { apiCall } from '../api/client';
import { Calendar, AlertCircle, Clock, PackageOpen, ChevronRight } from 'lucide-react';
import './Schedule.css';

const Schedule = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchItems();
  }, []);

  const fetchItems = async () => {
    try {
      // Fetch all items and filter them client-side
      // A dedicated backend endpoint /inventory/schedule would be more efficient for large datasets
      const data = await apiCall('/inventory/items');
      
      const scheduledItems = data.filter(item => 
        item.attributes && (item.attributes.remind_at || item.attributes.expiry_date)
      );
      
      // Sort by earliest date first
      scheduledItems.sort((a, b) => {
        const dateA = new Date(a.attributes.remind_at || a.attributes.expiry_date);
        const dateB = new Date(b.attributes.remind_at || b.attributes.expiry_date);
        return dateA - dateB;
      });

      setItems(scheduledItems);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const getStatusIndicator = (dateString) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffDays = (date - now) / (1000 * 60 * 60 * 24);

    if (diffDays < 0) return { color: 'var(--danger)', icon: <AlertCircle size={16} />, text: 'Expired / Overdue' };
    if (diffDays < 3) return { color: 'var(--warning)', icon: <Clock size={16} />, text: 'Upcoming soon' };
    return { color: 'var(--success)', icon: <Calendar size={16} />, text: 'Scheduled' };
  };

  return (
    <div className="schedule-page">
      <header className="page-header">
        <h1>Schedule & Reminders</h1>
        <p>Upcoming item expirations and reminders</p>
      </header>

      {loading ? (
        <div className="empty-state">Loading schedule...</div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <Calendar size={48} opacity={0.5} />
          <p>No upcoming schedules or expirations found.</p>
        </div>
      ) : (
        <div className="schedule-list">
          {items.map(item => {
            const targetDateStr = item.attributes.remind_at || item.attributes.expiry_date;
            const targetDate = new Date(targetDateStr).toLocaleDateString(undefined, { 
              year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' 
            });
            const status = getStatusIndicator(targetDateStr);

            return (
              <GlassCard key={item.id} className="schedule-card" hoverEffect>
                <div className="schedule-indicator" style={{ backgroundColor: status.color }}></div>
                
                {item.media && item.media.length > 0 ? (
                  <img 
                    src={(item.media.find(m => m.is_primary) || item.media[0]).original_url.replace('minio:9000', 'localhost:9010')} 
                    alt={item.name} 
                    className="schedule-img"
                  />
                ) : (
                  <div className="schedule-img-placeholder">
                    <PackageOpen size={24} />
                  </div>
                )}
                
                <div className="schedule-info">
                  <h3>{item.name}</h3>
                  <div className="schedule-meta">
                    <span className="badge category">{item.primary_category}</span>
                    {item.attributes.expiry_date && <span className="badge">Expiry: {item.attributes.expiry_date}</span>}
                    {item.attributes.remind_at && <span className="badge">Reminder: {item.attributes.remind_at}</span>}
                  </div>
                </div>

                <div className="schedule-date-box" style={{ color: status.color }}>
                  {status.icon}
                  <div className="date-text">
                    <span className="date-exact">{targetDate}</span>
                    <span className="date-relative">{status.text}</span>
                  </div>
                </div>

                <button className="icon-btn action-btn">
                  <ChevronRight size={20} />
                </button>
              </GlassCard>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default Schedule;
