export async function compressImage(file, maxSize = 1600, { rotation = 0, crop = null } = {}) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
    throw new Error('Поддерживаются JPEG, PNG и WebP.')
  if (file.size > 32 * 1024 * 1024)
    throw new Error('Фото больше 32 МБ. Уменьшите его перед загрузкой.')
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  try {
    if (bitmap.width * bitmap.height > 40000000)
      throw new Error('Фото больше 40 мегапикселей. Уменьшите его перед загрузкой.')
    const x = crop ? (bitmap.width * crop.x) / 100 : 0
    const y = crop ? (bitmap.height * crop.y) / 100 : 0
    const width = crop ? (bitmap.width * crop.width) / 100 : bitmap.width
    const height = crop ? (bitmap.height * crop.height) / 100 : bitmap.height
    if (
      ![x, y, width, height, rotation].every(Number.isFinite) ||
      x < 0 ||
      y < 0 ||
      width <= 0 ||
      height <= 0 ||
      x + width > bitmap.width + 1 ||
      y + height > bitmap.height + 1
    )
      throw new Error('Область обрезки выходит за пределы фото.')
    const swapped = Math.abs(rotation % 180) === 90
    const scale = Math.min(1, maxSize / Math.max(width, height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round((swapped ? height : width) * scale))
    canvas.height = Math.max(1, Math.round((swapped ? width : height) * scale))
    const context = canvas.getContext('2d')
    context.fillStyle = '#fff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.translate(canvas.width / 2, canvas.height / 2)
    context.rotate((rotation * Math.PI) / 180)
    context.drawImage(
      bitmap,
      x,
      y,
      width,
      height,
      (-width * scale) / 2,
      (-height * scale) / 2,
      width * scale,
      height * scale,
    )
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.8))
    if (!blob) throw new Error('Не удалось подготовить изображение.')
    return new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' })
  } finally {
    bitmap.close()
  }
}

function wav(buffer) {
  const view = new DataView(new ArrayBuffer(44 + buffer.length * 2))
  const text = (offset, value) =>
    [...value].forEach((letter, i) => view.setUint8(offset + i, letter.charCodeAt(0)))
  text(0, 'RIFF')
  view.setUint32(4, 36 + buffer.length * 2, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, 16000, true)
  view.setUint32(28, 32000, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, buffer.length * 2, true)
  const channel = buffer.getChannelData(0)
  for (let i = 0; i < channel.length; i++) {
    const sample = Math.max(-1, Math.min(1, channel[i]))
    view.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true)
  }
  return new File([view], 'recording.wav', { type: 'audio/wav' })
}
export async function prepareAudio(blob, from = 0, to = null) {
  if (blob.size > 32 * 1024 * 1024) throw new Error('Аудиофайл больше 32 МБ.')
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer())
    const end = to == null ? decoded.duration : Math.min(to, decoded.duration)
    if (!Number.isFinite(from) || !Number.isFinite(end) || from < 0 || end <= from)
      throw new Error('Проверьте начало и конец обрезки аудио.')
    if (end - from > 300) throw new Error('Запись должна быть не длиннее пяти минут.')
    const offline = new OfflineAudioContext(1, Math.ceil((end - from) * 16000), 16000)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start(0, from, end - from)
    return wav(await offline.startRendering())
  } finally {
    await context.close()
  }
}
export class AudioRecorder {
  async start() {
    if (!navigator.mediaDevices?.getUserMedia || !globalThis.MediaRecorder)
      throw new Error('Запись недоступна. Откройте localhost/HTTPS или прикрепите аудиофайл.')
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    this.chunks = []
    try {
      this.recorder = new MediaRecorder(this.stream)
      this.recorder.ondataavailable = (event) => {
        if (event.data.size) this.chunks.push(event.data)
      }
      this.recorder.start()
    } catch (error) {
      this.cancel()
      throw error
    }
  }
  stop() {
    return new Promise((resolve, reject) => {
      if (!this.recorder || this.recorder.state !== 'recording') {
        reject(new Error('Запись не начата.'))
        return
      }
      this.recorder.onstop = async () => {
        this.stream?.getTracks().forEach((track) => track.stop())
        try {
          resolve(await prepareAudio(new Blob(this.chunks, { type: this.recorder.mimeType })))
        } catch (error) {
          reject(error)
        } finally {
          this.stream = null
          this.recorder = null
        }
      }
      this.recorder.stop()
    })
  }
  cancel() {
    if (this.recorder) {
      this.recorder.onstop = null
      if (this.recorder.state === 'recording') this.recorder.stop()
    }
    this.stream?.getTracks().forEach((track) => track.stop())
    this.stream = this.recorder = null
  }
}
