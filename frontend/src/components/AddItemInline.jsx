import React, { useState, useEffect, useRef } from 'react';
import Button from './Button';
import Input from './Input';
import { apiCall } from '../api/client';
import { Mic, MicOff, Camera, FileAudio, X, Play, Square } from 'lucide-react';
import { recordAudio16kHzMono, downscaleImage } from '../utils/media';

const AddItemInline = ({ locationId: initialLocationId = null, showLocationSelector = false, onAdded }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [recorder, setRecorder] = useState(null);
  const [audioBlob, setAudioBlob] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [photos, setPhotos] = useState([]);
  const [photoPreviewUrls, setPhotoPreviewUrls] = useState([]);
  const [loading, setLoading] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);

  // Location selection state
  const [locations, setLocations] = useState([]);
  const [selectedLocId, setSelectedLocId] = useState(initialLocationId || "");
  const [newLocName, setNewLocName] = useState("");
  const [isCreatingLoc, setIsCreatingLoc] = useState(false);

  const fileInputRef = useRef(null);
  const timerRef = useRef(null);
  const canvasRef = useRef(null);
  const analyserRef = useRef(null);
  const animFrameRef = useRef(null);

  useEffect(() => {
    if (showLocationSelector) {
      apiCall('/inventory/locations').then(setLocations).catch(console.error);
    }
  }, [showLocationSelector]);

  // Update selectedLocId when initialLocationId changes (drill-down)
  useEffect(() => {
    if (initialLocationId) setSelectedLocId(initialLocationId);
  }, [initialLocationId]);

  const flattenLocations = (nodes, depth = 0) => {
    let result = [];
    nodes.forEach(n => {
      result.push({ ...n, depth });
      if (n.children) {
        result = result.concat(flattenLocations(n.children, depth + 1));
      }
    });
    return result;
  };

  const startRecording = async () => {
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
      setRecordingTime(0);

      timerRef.current = setInterval(() => {
        setRecordingTime(t => t + 1);
      }, 1000);

      // Waveform
      setTimeout(() => {
        if (canvasRef.current) {
          drawWaveform(analyser);
        }
      }, 50);
    } catch (err) {
      alert("Microphone access denied or error: " + err.message);
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
      ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#ef4444';
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
    if (recorder) {
      clearInterval(timerRef.current);
      cancelAnimationFrame(animFrameRef.current);
      const blob = await recorder.stop();
      setAudioBlob(blob);
      setAudioUrl(URL.createObjectURL(blob));
      setIsRecording(false);
    }
  };

  const clearAudio = () => {
    setAudioBlob(null);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setRecordingTime(0);
  };

  const handlePhotoSelect = async (e) => {
    const files = Array.from(e.target.files);
    if (photos.length + files.length > 3) {
      alert("Maximum 3 photos allowed.");
      return;
    }
    const processed = await Promise.all(files.map(f => downscaleImage(f)));
    const newPhotos = processed.map((b, i) => new File([b], `photo_${Date.now()}_${i}.jpg`, {type: 'image/jpeg'}));
    const newUrls = newPhotos.map(f => URL.createObjectURL(f));
    setPhotos([...photos, ...newPhotos]);
    setPhotoPreviewUrls([...photoPreviewUrls, ...newUrls]);
  };

  const removePhoto = (idx) => {
    URL.revokeObjectURL(photoPreviewUrls[idx]);
    setPhotos(photos.filter((_, i) => i !== idx));
    setPhotoPreviewUrls(photoPreviewUrls.filter((_, i) => i !== idx));
  };

  const handleSubmit = async () => {
    if (photos.length === 0) {
      alert("At least one photo is required to process an item.");
      return;
    }
    setLoading(true);
    try {
      let finalLocationId = selectedLocId;

      if (showLocationSelector && isCreatingLoc && newLocName.trim()) {
        const createdLoc = await apiCall('/inventory/locations', {
          method: 'POST',
          body: JSON.stringify({ name: newLocName })
        });
        finalLocationId = createdLoc.id;
      }

      const formData = new FormData();
      photos.forEach(p => formData.append('photos', p));
      if (audioBlob) {
        formData.append('audio', new File([audioBlob], 'audio.wav', {type: 'audio/wav'}));
      }

      let textComment = "";
      if (finalLocationId) {
        textComment = `I am adding this item. It should be stored in location_id: ${finalLocationId}`;
        formData.append('text_comment', textComment);
      } else {
        textComment = `I am adding this item.`;
        formData.append('text_comment', textComment);
      }

      await apiCall('/inventory/items/process', {
        method: 'POST',
        body: formData
      });

      setPhotos([]);
      setPhotoPreviewUrls([]);
      clearAudio();
      setNewLocName("");
      setIsCreatingLoc(false);
      alert("Item processing started! Check Tasks tab.");
      if (onAdded) onAdded();
    } catch (err) {
      alert("Error: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  const flatLocs = showLocationSelector ? flattenLocations(locations) : [];
  const formatTime = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

  return (
    <div className="add-item-inline">
      <h4>Add Item {initialLocationId ? '' : '(Root)'}</h4>

      {showLocationSelector && (
        <div style={{ marginBottom: '16px', display: 'flex', gap: '8px', alignItems: 'center' }}>
          {!isCreatingLoc ? (
            <>
              <select
                value={selectedLocId}
                onChange={(e) => setSelectedLocId(e.target.value)}
                style={{ padding: '8px', borderRadius: '4px', background: 'rgba(0,0,0,0.2)', color: 'white', border: '1px solid rgba(255,255,255,0.1)' }}
              >
                <option value="">No Location (Root)</option>
                {flatLocs.map(l => (
                  <option key={l.id} value={l.id}>
                    {'-'.repeat(l.depth)} {l.name}
                  </option>
                ))}
              </select>
              <Button variant="secondary" onClick={() => setIsCreatingLoc(true)}>+ New</Button>
            </>
          ) : (
            <>
              <Input
                placeholder="New location name"
                value={newLocName}
                onChange={(e) => setNewLocName(e.target.value)}
              />
              <Button variant="secondary" onClick={() => setIsCreatingLoc(false)}>Cancel</Button>
            </>
          )}
        </div>
      )}

      {/* Photo previews */}
      {photoPreviewUrls.length > 0 && (
        <div className="photo-previews">
          {photoPreviewUrls.map((url, i) => (
            <div key={i} className="photo-preview-item">
              <img src={url} alt={`Preview ${i+1}`} />
              <button className="remove-preview" onClick={() => removePhoto(i)}><X size={12}/></button>
            </div>
          ))}
        </div>
      )}

      {/* Audio preview / recording */}
      {isRecording && (
        <div className="recording-inline">
          <div className="rec-indicator">
            <Mic size={16} className="recording-pulse" />
            <span>Recording {formatTime(recordingTime)}</span>
          </div>
          <canvas ref={canvasRef} width={300} height={40} className="waveform-inline" />
        </div>
      )}

      {audioUrl && !isRecording && (
        <div className="audio-preview">
          <audio controls src={audioUrl} style={{height: '32px', flex: 1}} />
          <button className="remove-preview" onClick={clearAudio}><X size={12}/></button>
        </div>
      )}

      <div className="add-item-controls">
        <input
          type="file"
          accept="image/*"
          multiple
          ref={fileInputRef}
          style={{display: 'none'}}
          onChange={handlePhotoSelect}
        />
        <Button variant="secondary" onClick={() => fileInputRef.current?.click()} disabled={loading}>
          <Camera size={16}/> Photo {photos.length > 0 && `(${photos.length}/3)`}
        </Button>

        {!isRecording && !audioBlob && (
          <Button variant="secondary" onClick={startRecording} disabled={loading}>
            <Mic size={16}/> Record Voice
          </Button>
        )}
        {isRecording && (
          <Button variant="danger" onClick={stopRecording} disabled={loading}>
            <Square size={16}/> Stop
          </Button>
        )}
        {audioBlob && !isRecording && (
          <span className="audio-ready"><FileAudio size={16} /> Audio saved</span>
        )}

        <Button onClick={handleSubmit} disabled={loading || photos.length === 0}>
          {loading ? "Processing..." : "Process Item"}
        </Button>
      </div>
    </div>
  );
};

export default AddItemInline;
