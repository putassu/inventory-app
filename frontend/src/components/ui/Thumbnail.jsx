import { useState, useEffect, useRef } from 'react'
import { loadImage } from '../../api/images'
import { Image as ImageIcon } from 'lucide-react'
export function Thumbnail({
  photoId,
  mediaId,
  size = 'md',
  className = '',
  alt = 'Фотография',
  full = false,
}) {
  const id = photoId || mediaId
  const box = useRef(null)
  const [image, setImage] = useState(null)
  const dim =
    typeof size === 'number' ? size : { sm: 40, md: 64, lg: 96 }[size] || parseInt(size, 10) || 64
  useEffect(() => {
    if (!id) return
    const controller = new AbortController()
    let objectUrl
    let started = false
    function load() {
      if (started) return
      started = true
      loadImage(id, controller.signal)
        .then((blob) => {
          if (controller.signal.aborted) return
          objectUrl = URL.createObjectURL(blob)
          setImage({ id, url: objectUrl })
        })
        .catch(() => {})
    }
    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(
            (entries) => {
              if (entries.some((entry) => entry.isIntersecting)) load()
            },
            { rootMargin: '100px' },
          )
    if (observer) observer.observe(box.current)
    else load()
    return () => {
      controller.abort()
      observer?.disconnect()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [id])
  return (
    <span
      ref={box}
      className={`thumbnail ${className}`}
      style={{ width: full ? '100%' : dim, height: full ? 'auto' : dim, minHeight: dim }}
    >
      {id && image?.id === id ? (
        <img
          src={image.url}
          alt={alt}
          style={{
            width: '100%',
            height: full ? 'auto' : '100%',
            objectFit: full ? 'contain' : 'cover',
          }}
        />
      ) : (
        <ImageIcon aria-label="Нет миниатюры" size={24} />
      )}
    </span>
  )
}
