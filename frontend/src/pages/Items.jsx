import React, { useState, useEffect } from 'react';
import GlassCard from '../components/GlassCard';
import { apiCall } from '../api/client';
import { PackageOpen, Filter, Search as SearchIcon, Plus, Minus, X, Trash2 } from 'lucide-react';
import AddItemInline from '../components/AddItemInline';
import ItemForm from '../components/ItemForm';
import './Items.css';

const Items = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedItem, setSelectedItem] = useState(null);
  const [showManualAdd, setShowManualAdd] = useState(false);

  const fetchItems = async () => {
    try {
      const data = await apiCall('/inventory/items');
      setItems(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
  }, []);

  const filteredItems = items.filter(item => 
    (item.name && item.name.toLowerCase().includes(searchQuery.toLowerCase())) || 
    (item.primary_category && item.primary_category.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const handleAdjustQuantity = async (e, item, delta) => {
    e.stopPropagation();
    const currentQty = parseFloat(item.quantity) || 0;
    // Prevent dropping below 0
    if (currentQty + delta < 0) return;
    
    // Optimistic UI update
    setItems(items.map(i => 
      i.id === item.id ? { ...i, quantity: currentQty + delta } : i
    ));

    try {
      await apiCall(`/inventory/items/${item.id}/adjust?amount=${delta}`, { method: 'PUT' });
      // We don't fetchItems() immediately to keep UI smooth, but you could.
    } catch (err) {
      console.error(err);
      fetchItems(); // Revert on failure
    }
  };

  const handleDeleteItem = async (e, item) => {
    e.stopPropagation();
    if (!window.confirm(`Are you sure you want to delete "${item.name}"?`)) return;

    try {
      await apiCall(`/inventory/items/${item.id}`, { method: 'DELETE' });
      if (selectedItem?.id === item.id) setSelectedItem(null);
      fetchItems();
    } catch (err) {
      alert("Failed to delete item: " + err.message);
    }
  };

  const handleManualAddSubmit = async (formData) => {
    try {
      await apiCall('/inventory/items', {
        method: 'POST',
        body: JSON.stringify(formData)
      });
      setShowManualAdd(false);
      fetchItems();
    } catch (err) {
      alert("Failed to create item: " + err.message);
    }
  };

  const renderModal = () => {
    if (!selectedItem) return null;
    return (
      <div className="item-modal-overlay" onClick={() => setSelectedItem(null)}>
        <GlassCard className="item-modal-content" onClick={(e) => e.stopPropagation()}>
          <button className="close-modal" onClick={() => setSelectedItem(null)}>
            <X size={24} />
          </button>
          
          <div className="modal-header">
            <h2>{selectedItem.name}</h2>
            <div className="modal-badges">
              <span className="badge category">{selectedItem.primary_category}</span>
              <span className="badge status-badge">{selectedItem.status}</span>
              <button className="icon-btn delete-btn" onClick={(e) => handleDeleteItem(e, selectedItem)} title="Delete Item">
                <Trash2 size={16} />
              </button>
            </div>
          </div>

          <div className="modal-body">
            {selectedItem.media && selectedItem.media.length > 0 ? (
              <div className="modal-image-container">
                <img 
                  src={(selectedItem.media.find(m => m.is_primary) || selectedItem.media[0]).original_url.replace('minio:9000', 'localhost:9010')} 
                  alt={selectedItem.name} 
                  className="modal-image"
                />
              </div>
            ) : (
              <div className="modal-image-placeholder">
                <PackageOpen size={64} opacity={0.3} />
              </div>
            )}
            
            <div className="modal-info">
              <div className="info-row">
                <span className="info-label">Quantity:</span>
                <span className="info-value">{selectedItem.quantity} {selectedItem.unit_of_measure}</span>
              </div>
              <div className="info-row">
                <span className="info-label">Tags:</span>
                <span className="info-value">
                  {selectedItem.tags && selectedItem.tags.length > 0 ? selectedItem.tags.join(', ') : 'None'}
                </span>
              </div>
              <div className="info-row">
                <span className="info-label">Attributes:</span>
                <div className="attributes-grid">
                  {selectedItem.attributes && Object.entries(selectedItem.attributes).map(([k, v]) => (
                    <div key={k} className="attribute-badge">
                      <strong>{k}:</strong> {String(v)}
                    </div>
                  ))}
                </div>
              </div>
              {selectedItem.generated_desc && (
                <div className="info-row description-row">
                  <span className="info-label">Description:</span>
                  <p className="info-text">{selectedItem.generated_desc}</p>
                </div>
              )}
            </div>
          </div>
        </GlassCard>
      </div>
    );
  };

  return (
    <div className="items-page">
      <header className="page-header">
        <h1>Inventory Items</h1>
        <p>Browse and manage your possessions</p>
      </header>

      <GlassCard className="mb-4">
        <AddItemInline showLocationSelector={true} onAdded={fetchItems} />
      </GlassCard>

      <div className="items-toolbar">
        <div className="search-box">
          <SearchIcon size={18} className="search-icon" />
          <input 
            type="text" 
            placeholder="Filter by name or category..." 
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className="toolbar-actions">
          <button className="filter-btn"><Filter size={18} /> Filters</button>
          <button className="btn primary" onClick={() => setShowManualAdd(true)}>
            <Plus size={18} /> Add Manually
          </button>
        </div>
      </div>

      {loading ? (
        <div className="empty-state">Loading items...</div>
      ) : filteredItems.length === 0 ? (
        <div className="empty-state">
          <PackageOpen size={48} opacity={0.5} />
          <p>No items found.</p>
        </div>
      ) : (
        <div className="items-grid">
          {filteredItems.map(item => (
            <GlassCard key={item.id} className="item-card" hoverEffect onClick={() => setSelectedItem(item)}>
              {item.media && item.media.length > 0 ? (
                <div className="item-image-container">
                  <img 
                    src={(item.media.find(m => m.is_primary) || item.media[0]).original_url.replace('minio:9000', 'localhost:9010')} 
                    alt={item.name} 
                    className="item-image"
                  />
                </div>
              ) : (
                <div className="item-image-placeholder">
                  <PackageOpen size={32} />
                </div>
              )}
              <div className="item-details">
                <h3>
                   <span className={`status-dot ${item.status === 'failed' || item.status === 'user_action_required' ? 'red' : item.status === 'completed' ? 'green' : 'yellow'}`} title={item.status}></span>
                   {item.name}
                </h3>
                <div className="item-meta">
                  <span className="badge category">{item.primary_category}</span>
                  <div className="item-actions-row">
                    <div className="qty-controls" onClick={(e) => e.stopPropagation()}>
                      <button className="qty-btn" onClick={(e) => handleAdjustQuantity(e, item, -1)}><Minus size={12} /></button>
                      <span className="badge qty">{item.quantity}</span>
                      <button className="qty-btn" onClick={(e) => handleAdjustQuantity(e, item, 1)}><Plus size={12} /></button>
                    </div>
                    <button className="icon-btn delete-btn-small" onClick={(e) => handleDeleteItem(e, item)} title="Delete">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              </div>
            </GlassCard>
          ))}
        </div>
      )}
      
      {renderModal()}

      {showManualAdd && (
        <div className="item-modal-overlay" onClick={() => setShowManualAdd(false)}>
          <GlassCard className="item-modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Add Item Manually</h2>
              <button className="close-modal" onClick={() => setShowManualAdd(false)}>
                <X size={24} />
              </button>
            </div>
            <div className="modal-body">
              <ItemForm 
                onSubmit={handleManualAddSubmit}
                onCancel={() => setShowManualAdd(false)}
                submitLabel="Create Item"
              />
            </div>
          </GlassCard>
        </div>
      )}
    </div>
  );
};

export default Items;
