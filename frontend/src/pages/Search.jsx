import React, { useState, useEffect } from 'react';
import GlassCard from '../components/GlassCard';
import Input from '../components/Input';
import Button from '../components/Button';
import { apiCall } from '../api/client';
import { Search as SearchIcon, Upload, PackageOpen, Filter, SortAsc, SortDesc, MapPin, X } from 'lucide-react';
import './Search.css';

const CATEGORIES = [
  '', 'MEDICINES', 'DOCUMENTS', 'CLOTHES', 'TECH', 'FOOD',
  'DISHES', 'COSMETICS', 'HOUSEHOLD', 'HOBBY', 'OTHER'
];

const Search = () => {
  const [query, setQuery] = useState('');
  const [photo, setPhoto] = useState(null);
  const [results, setResults] = useState({ items: [], locations: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Filters
  const [showFilters, setShowFilters] = useState(false);
  const [category, setCategory] = useState('');
  const [tagsFilter, setTagsFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [sortBy, setSortBy] = useState('updated_at');
  const [sortDir, setSortDir] = useState('desc');

  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    setLoading(true);
    setError('');

    try {
      if (photo) {
        // Multimodal LLM search
        const formData = new FormData();
        if (query) formData.append('text_query', query);
        formData.append('photo', photo);
        const data = await apiCall('/inventory/search/multimodal', {
          method: 'POST',
          body: formData
        });
        setResults({ items: data, locations: [] });
      } else {
        // Fast DB search with filters — NO LLM
        const params = new URLSearchParams();
        if (query.trim()) params.set('query', query.trim());
        if (category) params.set('category', category);
        if (tagsFilter.trim()) params.set('tags', tagsFilter.trim());
        if (dateFrom) params.set('date_from', dateFrom);
        if (dateTo) params.set('date_to', dateTo);
        params.set('sort_by', sortBy);
        params.set('sort_dir', sortDir);
        params.set('limit', '100');

        const data = await apiCall(`/inventory/search?${params.toString()}`);
        setResults(data);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Auto-search when filters change (debounced)
  useEffect(() => {
    if (!photo) {
      const t = setTimeout(() => handleSearch(), 300);
      return () => clearTimeout(t);
    }
  }, [query, category, tagsFilter, dateFrom, dateTo, sortBy, sortDir]);

  const clearFilters = () => {
    setCategory('');
    setTagsFilter('');
    setDateFrom('');
    setDateTo('');
    setSortBy('updated_at');
    setSortDir('desc');
  };

  const activeFilterCount = [category, tagsFilter, dateFrom, dateTo].filter(Boolean).length;

  return (
    <div className="search-page">
      <header className="page-header">
        <h1>Global Search</h1>
        <p>Find items and locations — instant text search, or attach media for AI-powered semantic search</p>
      </header>

      <GlassCard className="search-box-card">
        <form onSubmit={handleSearch} className="search-form">
          <Input
            placeholder="Search items, tags, descriptions..."
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <div className="file-upload-wrapper">
            <input
              type="file"
              id="file-upload"
              accept="image/*"
              onChange={e => setPhoto(e.target.files[0])}
            />
            <label htmlFor="file-upload" className="file-upload-label">
              <Upload size={18} /> {photo ? photo.name : 'AI Image Search'}
            </label>
            {photo && (
              <button type="button" className="clear-photo" onClick={() => setPhoto(null)}>
                <X size={14}/>
              </button>
            )}
          </div>
          <button
            type="button"
            className={`filter-btn ${showFilters ? 'active' : ''}`}
            onClick={() => setShowFilters(!showFilters)}
          >
            <Filter size={16} /> Filters {activeFilterCount > 0 && <span className="filter-count">{activeFilterCount}</span>}
          </button>
          <Button type="submit" disabled={loading}>
            <SearchIcon size={18} /> {loading ? 'Searching...' : 'Search'}
          </Button>
        </form>

        {showFilters && (
          <div className="filters-panel">
            <div className="filter-row">
              <label>Category</label>
              <select value={category} onChange={e => setCategory(e.target.value)}>
                <option value="">All Categories</option>
                {CATEGORIES.filter(Boolean).map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div className="filter-row">
              <label>Tags</label>
              <input type="text" placeholder="e.g. vitamins, kitchen" value={tagsFilter} onChange={e => setTagsFilter(e.target.value)} />
            </div>
            <div className="filter-row">
              <label>Date From</label>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
            </div>
            <div className="filter-row">
              <label>Date To</label>
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
            </div>
            <div className="filter-row">
              <label>Sort By</label>
              <select value={sortBy} onChange={e => setSortBy(e.target.value)}>
                <option value="updated_at">Last Updated</option>
                <option value="created_at">Created</option>
                <option value="name">Name</option>
                <option value="primary_category">Category</option>
              </select>
              <button type="button" className="sort-toggle" onClick={() => setSortDir(d => d === 'asc' ? 'desc' : 'asc')}>
                {sortDir === 'asc' ? <SortAsc size={16}/> : <SortDesc size={16}/>}
              </button>
            </div>
            <button type="button" className="clear-filters-btn" onClick={clearFilters}>Clear All Filters</button>
          </div>
        )}
        {error && <div className="error-text">{error}</div>}
      </GlassCard>

      <div className="search-results">
        <h2>Items ({(results.items || []).length})</h2>
        {(results.items || []).length === 0 && !loading && (
          <div className="empty-state">No items match your query.</div>
        )}
        <div className="items-grid">
          {(results.items || []).map(item => (
            <GlassCard key={item.id} className="item-card" hoverEffect>
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
                  <span className={`status-dot ${item.status === 'failed' || item.status === 'user_action_required' ? 'red' : item.status === 'completed' ? 'green' : 'yellow'}`}></span>
                  {item.name || 'Processing...'}
                </h3>
                <p className="item-desc">{item.generated_desc}</p>
                <div className="item-meta">
                  <span className="badge category">{item.primary_category}</span>
                  {item.tags && item.tags.slice(0, 3).map(t => (
                    <span key={t} className="badge tag">{t}</span>
                  ))}
                </div>
              </div>
            </GlassCard>
          ))}
        </div>

        <h2 style={{marginTop: '30px'}}>
          <MapPin size={20} style={{verticalAlign: 'middle', marginRight: '6px'}}/>
          Locations ({(results.locations || []).length})
        </h2>
        {(results.locations || []).length === 0 && !loading && (
          <div className="empty-state">No locations match your query.</div>
        )}
        <div className="items-grid">
          {(results.locations || []).map(loc => (
            <GlassCard key={loc.id} className="item-card" hoverEffect>
              <div className="item-details">
                <h3><MapPin size={16}/> {loc.name}</h3>
                <p className="item-desc">{loc.description}</p>
              </div>
            </GlassCard>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Search;
