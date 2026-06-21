import React, { useState, useEffect, useRef, useCallback } from 'react';
import GlassCard from '../components/GlassCard';
import Button from '../components/Button';
import Input from '../components/Input';
import { apiCall } from '../api/client';
import { MapPin, Plus, Trash2, ChevronLeft, Mic, MicOff, Camera, FileAudio, Image as ImageIcon, PackageOpen, Search as SearchIcon } from 'lucide-react';
import { recordAudio16kHzMono, downscaleImage } from '../utils/media';
import AddItemInline from '../components/AddItemInline';
import './Locations.css';


const Locations = () => {
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [path, setPath] = useState([]);
  const [newLocName, setNewLocName] = useState("");

  // Items inside current location
  const [locationItems, setLocationItems] = useState([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemSearch, setItemSearch] = useState("");

  // Audio recording state
  const [recordingLocId, setRecordingLocId] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  const [recorder, setRecorder] = useState(null);
  const [recordingTime, setRecordingTime] = useState(0);
  const timerRef = useRef(null);
  const canvasRef = useRef(null);
  const analyserRef = useRef(null);
  const animFrameRef = useRef(null);

  const fetchLocations = async () => {
    try {
      const data = await apiCall('/inventory/locations');
      setLocations(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const currentParent = path.length > 0 ? path[path.length - 1] : null;

  // Fetch items inside the current location
  const fetchLocationItems = useCallback(async () => {
    if (!currentParent) {
      setLocationItems([]);
      return;
    }
    setLoadingItems(true);
    try {
      const data = await apiCall(`/inventory/items?location_id=${currentParent.id}`);
      setLocationItems(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingItems(false);
    }
  }, [currentParent]);

  useEffect(() => {
    fetchLocations();
  }, []);

  useEffect(() => {
    fetchLocationItems();
  }, [fetchLocationItems]);

  const handleAddLocation = async () => {
    if (!newLocName.trim()) return;
    const parentId = currentParent ? currentParent.id : null;
    try {
      await apiCall('/inventory/locations', {
        method: 'POST',
        body: JSON.stringify({ name: newLocName, parent_location_id: parentId })
      });
      setNewLocName("");
      fetchLocations();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    if (!confirm('Delete this location?')) return;
    try {
      await apiCall(`/inventory/locations/${id}?cascade=false`, { method: 'DELETE' });
      if (path.length > 0 && path[path.length - 1].id === id) {
        setPath(path.slice(0, -1));
      }
      fetchLocations();
    } catch (err) {
      alert(err.message);
    }
  };

  const handlePhotoUpload = async (locId, files) => {
    if (files.length === 0) return;
    const fd = new FormData();
    for (const f of files) {
      fd.append('photos', f);
    }
    try {
      await apiCall(`/inventory/locations/${locId}/media`, { method: 'POST', body: fd });
      fetchLocations();
    } catch (err) {
      alert('Upload failed: ' + err.message);
    }
  };

  // --- Audio recording with waveform ---
  const startRecording = async (locId) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;

      const rec = await recordAudio16kHzMono();
      setRecorder(rec);
      rec.start();
      setIsRecording(true);
      setRecordingLocId(locId);
      setRecordingTime(0);

      // Start timer
      timerRef.current = setInterval(() => {
        setRecordingTime(t => t + 1);
      }, 1000);

      // Start waveform drawing after canvas mounts
      setTimeout(() => {
        if (canvasRef.current) {
          drawWaveform(analyser);
        }
      }, 50);
    } catch (err) {
      alert("Microphone error: " + err.message);
    }
  };

  const drawWaveform = (analyser) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const draw = () => {
      animFrameRef.current = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(dataArray);
      ctx.fillStyle = 'rgba(15, 23, 42, 0.8)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#10b981';
      ctx.beginPath();
      const sliceWidth = canvas.width / bufferLength;
      let x = 0;
      for (let i = 0; i < bufferLength; i++) {
        const v = dataArray[i] / 128.0;
        const y = v * canvas.height / 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceWidth;
      }
      ctx.lineTo(canvas.width, canvas.height / 2);
      ctx.stroke();
    };
    draw();
  };

  const stopRecording = async () => {
    if (!recorder) return;
    clearInterval(timerRef.current);
    cancelAnimationFrame(animFrameRef.current);
    const blob = await recorder.stop();
    setIsRecording(false);

    // Upload immediately
    const fd = new FormData();
    fd.append('audio', new File([blob], 'voice_note.wav', { type: 'audio/wav' }));
    try {
      await apiCall(`/inventory/locations/${recordingLocId}/media`, { method: 'POST', body: fd });
      fetchLocations();
    } catch (err) {
      alert('Audio upload failed: ' + err.message);
    }
    setRecordingLocId(null);
    setRecordingTime(0);
  };

  // Find children of current context
  const getCurrentChildren = () => {
    if (path.length === 0) return locations;
    let current = locations;
    let node = null;
    for (const p of path) {
      node = current.find(n => n.id === p.id);
      if (!node) return [];
      current = node.children || [];
    }
    return current;
  };

  const currentChildren = getCurrentChildren();

  // Filter items by local search
  const filteredItems = locationItems.filter(item =>
    !itemSearch.trim() ||
    (item.name && item.name.toLowerCase().includes(itemSearch.toLowerCase())) ||
    (item.primary_category && item.primary_category.toLowerCase().includes(itemSearch.toLowerCase())) ||
    (item.tags && item.tags.some(t => t.toLowerCase().includes(itemSearch.toLowerCase())))
  );

  const formatTime = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

  return (
    <div className="locations-page">
      <header className="page-header">
        <h1>{currentParent ? currentParent.name : 'Storage Locations'}</h1>
        <div className="breadcrumbs">
          <Button variant="secondary" onClick={() => setPath([])} disabled={path.length === 0}>Root</Button>
          {path.map((node, i) => (
            <React.Fragment key={node.id}>
              <ChevronLeft size={16} style={{margin: '0 8px', transform: 'rotate(180deg)'}}/>
              <Button variant="secondary" onClick={() => setPath(path.slice(0, i + 1))}>{node.name}</Button>
            </React.Fragment>
          ))}
        </div>
      </header>

      {/* Audio recording overlay */}
      {isRecording && (
        <GlassCard className="recording-overlay">
          <div className="recording-header">
            <Mic size={20} className="recording-pulse" />
            <span>Recording... {formatTime(recordingTime)}</span>
          </div>
          <canvas ref={canvasRef} width={400} height={60} className="waveform-canvas" />
          <Button variant="danger" onClick={stopRecording}>
            <MicOff size={16} /> Stop & Save
          </Button>
        </GlassCard>
      )}

      <div className="locations-grid">
        {loading ? (
          <div className="empty-state">Loading tree...</div>
        ) : (
          <>
            {currentChildren.map(loc => (
              <GlassCard
                key={loc.id}
                className="location-card-square cursor-pointer"
                onClick={() => setPath([...path, loc])}
              >
                <div className="loc-card-header">
                  <h3>
                    <span className={`status-indicator ${loc.status === 'user_action_required' ? 'red' : 'green'}`}></span>
                    <MapPin size={18}/> {loc.name}
                  </h3>
                  <button className="icon-btn danger" onClick={(e) => handleDelete(loc.id, e)}>
                    <Trash2 size={16}/>
                  </button>
                </div>

                {loc.photos && loc.photos.length > 0 && (
                  <div className="loc-photos">
                    {loc.photos.map(p => (
                      <img key={p.id} src={(p.preview_url || p.original_url).replace('minio:9000', 'localhost:9010')} alt="Location" className="loc-photo-thumb" />
                    ))}
                  </div>
                )}

                {loc.audio_url && (
                  <div className="loc-audio" onClick={e => e.stopPropagation()}>
                    <audio controls src={loc.audio_url.replace('minio:9000', 'localhost:9010')} style={{height: '28px', width: '100%'}}/>
                  </div>
                )}

                <div className="loc-media-actions" onClick={e => e.stopPropagation()}>
                  <label className="icon-btn" title="Add photo">
                    <ImageIcon size={14}/>
                    <input type="file" hidden accept="image/*" multiple onChange={(e) => handlePhotoUpload(loc.id, Array.from(e.target.files))} />
                  </label>
                  <button className="icon-btn" title="Record audio" onClick={() => startRecording(loc.id)}>
                    <Mic size={14}/>
                  </button>
                </div>

                {loc.children && loc.children.length > 0 && (
                  <div className="loc-children-preview">
                    {loc.children.slice(0, 4).map(child => (
                      <div key={child.id} className="loc-mini-square">
                        <span className={`status-dot ${child.status === 'user_action_required' ? 'red' : 'green'}`}></span>
                        {child.name}
                      </div>
                    ))}
                    {loc.children.length > 4 && (
                      <div className="loc-mini-square more">+{loc.children.length - 4}</div>
                    )}
                  </div>
                )}
                {(!loc.children || loc.children.length === 0) && (
                  <div className="loc-empty-preview">Empty</div>
                )}
              </GlassCard>
            ))}

            <GlassCard className="location-card-square add-new">
              <h3>Create New</h3>
              <Input
                placeholder="Location Name"
                value={newLocName}
                onChange={(e) => setNewLocName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddLocation()}
              />
              <Button onClick={handleAddLocation}><Plus size={16}/> Add</Button>
            </GlassCard>
          </>
        )}
      </div>

      {/* Items inside current location */}
      {currentParent && (
        <div className="location-items-section">
          <GlassCard>
            <div className="loc-items-header">
              <h2>Items in "{currentParent.name}"</h2>
              <div className="search-box" style={{maxWidth: '300px'}}>
                <SearchIcon size={16} className="search-icon" />
                <input
                  type="text"
                  placeholder="Filter items..."
                  value={itemSearch}
                  onChange={e => setItemSearch(e.target.value)}
                />
              </div>
            </div>

            {loadingItems ? (
              <div className="empty-state">Loading items...</div>
            ) : filteredItems.length === 0 ? (
              <div className="empty-state"><PackageOpen size={32} opacity={0.5}/> <p>No items in this location.</p></div>
            ) : (
              <div className="items-grid">
                {filteredItems.map(item => (
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
                      <div className="item-image-placeholder"><PackageOpen size={24}/></div>
                    )}
                    <div className="item-details">
                      <h3>
                        <span className={`status-dot ${item.status === 'failed' || item.status === 'user_action_required' ? 'red' : item.status === 'completed' ? 'green' : 'yellow'}`} title={item.status}></span>
                        {item.name || 'Processing...'}
                      </h3>
                      <div className="item-meta">
                        <span className="badge category">{item.primary_category}</span>
                        <span className="badge qty">Qty: {item.quantity}</span>
                      </div>
                    </div>
                  </GlassCard>
                ))}
              </div>
            )}
          </GlassCard>

          <GlassCard className="mt-20">
            <AddItemInline locationId={currentParent.id} onAdded={() => { fetchLocationItems(); fetchLocations(); }} />
          </GlassCard>
        </div>
      )}

      {!currentParent && (
        <GlassCard className="mt-20">
          <AddItemInline onAdded={() => { fetchLocations(); }} />
        </GlassCard>
      )}
    </div>
  );
};

export default Locations;
