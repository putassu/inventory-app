import { api, getSession } from './client'
let running = 0
const queue = []
function drain() {
  while (running < 3 && queue.length) {
    const job = queue.shift()
    if (job.signal.aborted || job.scope !== getSession().generation) {
      job.reject(new DOMException('Отменено', 'AbortError'))
      continue
    }
    running++
    api(`/media/${job.id}/download`, { blob: true, signal: job.signal })
      .then(job.resolve, job.reject)
      .finally(() => {
        running--
        drain()
      })
  }
}
export function loadImage(id, signal) {
  return new Promise((resolve, reject) => {
    queue.push({ id, signal, scope: getSession().generation, resolve, reject })
    drain()
  })
}
