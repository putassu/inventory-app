import React, { useState, useEffect } from 'react';
import Button from './Button';
import { apiCall } from '../api/client';
import { Plus, X, Trash } from 'lucide-react';
import './ItemForm.css';

const CATEGORIES = [
  'MEDICINES', 'DOCUMENTS', 'CLOTHES', 'TECH', 'FOOD', 
  'DISHES', 'COSMETICS', 'HOUSEHOLD', 'HOBBY', 'OTHER'
];

const flattenLocations = (nodes, prefix = '') => {
  let list = [];
  for (let node of nodes) {
    list.push({ id: node.id, name: `${prefix}${node.name}` });
    if (node.children && node.children.length > 0) {
      list = list.concat(flattenLocations(node.children, `${prefix}${node.name} > `));
    }
  }
  return list;
};

const ItemForm = ({ initialData, onSubmit, onCancel, submitLabel = 'Save' }) => {
  const [formData, setFormData] = useState({
    name: '',
    primary_category: 'OTHER',
    location_id: '',
    quantity: 1,
    unit_of_measure: 'pcs',
    tags: '',
    attributes: {}
  });
  
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [attrKey, setAttrKey] = useState('');
  const [attrVal, setAttrVal] = useState('');

  useEffect(() => {
    apiCall('/inventory/locations').then(tree => {
      setLocations(flattenLocations(tree));
    }).catch(console.error);
  }, []);

  useEffect(() => {
    if (initialData) {
      setFormData({
        name: initialData.name || '',
        primary_category: initialData.primary_category || 'OTHER',
        location_id: initialData.location?.id || initialData.location_id || '',
        quantity: initialData.quantity || 1,
        unit_of_measure: initialData.unit_of_measure || 'pcs',
        tags: Array.isArray(initialData.tags) ? initialData.tags.join(', ') : (initialData.tags || ''),
        attributes: initialData.attributes || {}
      });
    }
  }, [initialData]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleAddAttribute = () => {
    if (attrKey.trim()) {
      setFormData(prev => ({
        ...prev,
        attributes: { ...prev.attributes, [attrKey.trim()]: attrVal }
      }));
      setAttrKey('');
      setAttrVal('');
    }
  };

  const handleRemoveAttribute = (key) => {
    setFormData(prev => {
      const newAttr = { ...prev.attributes };
      delete newAttr[key];
      return { ...prev, attributes: newAttr };
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = {
      ...formData,
      quantity: parseFloat(formData.quantity) || 1,
      tags: formData.tags ? formData.tags.split(',').map(t => t.trim()).filter(Boolean) : [],
      location_id: formData.location_id || null
    };
    onSubmit(payload);
  };

  return (
    <form className="item-form" onSubmit={handleSubmit}>
      <div className="form-group">
        <label>Название</label>
        <input 
          type="text" 
          name="name" 
          value={formData.name} 
          onChange={handleChange} 
          required 
          placeholder="Например: Аспирин 500мг"
        />
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>Категория</label>
          <select name="primary_category" value={formData.primary_category} onChange={handleChange}>
            {CATEGORIES.map(cat => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        </div>
        
        <div className="form-group">
          <label>Локация</label>
          <select name="location_id" value={formData.location_id} onChange={handleChange}>
            <option value="">-- Без локации --</option>
            {locations.map(loc => (
              <option key={loc.id} value={loc.id}>{loc.name}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>Количество</label>
          <input 
            type="number" 
            name="quantity" 
            value={formData.quantity} 
            onChange={handleChange} 
            min="0" step="0.1"
          />
        </div>
        <div className="form-group">
          <label>Ед. изм.</label>
          <input 
            type="text" 
            name="unit_of_measure" 
            value={formData.unit_of_measure} 
            onChange={handleChange} 
            placeholder="pcs, mg, ml..."
          />
        </div>
      </div>

      <div className="form-group">
        <label>Теги (через запятую)</label>
        <input 
          type="text" 
          name="tags" 
          value={formData.tags} 
          onChange={handleChange} 
          placeholder="лекарства, обезболивающее..."
        />
      </div>

      <div className="attributes-section">
        <label>Дополнительные атрибуты</label>
        {Object.keys(formData.attributes).length > 0 && (
          <div className="attributes-list">
            {Object.entries(formData.attributes).map(([k, v]) => (
              <div key={k} className="attr-item">
                <span className="attr-name">{k}</span>
                <span className="attr-val">{String(v)}</span>
                <button type="button" onClick={() => handleRemoveAttribute(k)}><X size={14} /></button>
              </div>
            ))}
          </div>
        )}
        <div className="attr-add-row">
          <input 
            type="text" 
            placeholder="Название (например: expiry_date)" 
            value={attrKey} 
            onChange={e => setAttrKey(e.target.value)}
          />
          <input 
            type="text" 
            placeholder="Значение" 
            value={attrVal} 
            onChange={e => setAttrVal(e.target.value)}
          />
          <button type="button" className="add-attr-btn" onClick={handleAddAttribute}>
            <Plus size={16} />
          </button>
        </div>
      </div>

      <div className="form-actions">
        {onCancel && <Button variant="secondary" onClick={onCancel}>Отмена</Button>}
        <Button variant="primary" type="submit">{submitLabel}</Button>
      </div>
    </form>
  );
};

export default ItemForm;
