import { randomId } from '../utils/id'
import { useCallback, useRef, useState } from 'react'
import { uploadMedia } from '../api/media'

export function usePhotoUpload(initialPhotos = []) {
  const [photos, setPhotos] = useState(initialPhotos)
  const [preparing, setPreparing] = useState(false)
  const uploads = useRef(new Map())
  const onMediaCaptured = useCallback(({ files }) => setPhotos(files || []), [])
  async function upload(policy = 'local_only') {
    const ids = []
    for (const file of photos) {
      if (!uploads.current.has(file)) uploads.current.set(file, {})
      const entry = (uploads.current.get(file)[policy] ||= { key: randomId() })
      entry.media ||= await uploadMedia(file, policy, true, entry.key)
      ids.push(entry.media.media_id)
    }
    return ids
  }
  return {
    photos,
    upload,
    preparing,
    capture: { photosOnly: true, initialPhotos, onMediaCaptured, onBusyChange: setPreparing },
  }
}
