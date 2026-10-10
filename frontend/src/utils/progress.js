const phases = [
  { key: 'upload', name: 'Приём файлов', stages: ['upload_verified'], color: '#2563eb' },
  { key: 'media', name: 'Подготовка', stages: ['media'], color: '#0891b2' },
  { key: 'audio', name: 'Распознавание голоса', stages: ['audio'], color: '#7c3aed' },
  {
    key: 'privacy',
    name: 'Проверка приватности',
    stages: ['privacy_asr', 'gatekeeper'],
    color: '#c026d3',
  },
  {
    key: 'extraction',
    name: 'Распознавание вещи',
    stages: ['extraction', 'cloud_extraction', 'candidates'],
    color: '#ea580c',
  },
  {
    key: 'review',
    name: 'Проверка человеком',
    stages: ['review_ready', 'conflict'],
    color: '#ca8a04',
  },
  {
    key: 'save',
    name: 'Сохранение',
    stages: ['confirmation_queued', 'apply', 'saved', 'apply_failed'],
    color: '#16a34a',
  },
]

export function taskPhases(task) {
  const history = task.progress?.history || []
  const current = task.stage || task.progress?.current?.stage
  const seen = new Set([current, ...history.map((entry) => entry.stage)])
  const plan = phases.filter((phase) => {
    if (task.purpose === 'ocr' && ['privacy', 'extraction', 'review', 'save'].includes(phase.key))
      return false
    if (phase.key === 'audio') return task.input_mode?.includes('audio') || seen.has('audio')
    if (task.input_mode === 'manual' && ['privacy', 'extraction'].includes(phase.key)) return false
    return true
  })
  if (task.purpose === 'ocr')
    plan.push({
      key: 'ocr',
      name: 'Распознавание текста',
      stages: ['ocr', 'ocr_ready'],
      color: '#ea580c',
    })
  if (seen.has('search_ready'))
    plan.splice(-2, 2, {
      key: 'search',
      name: 'Результат поиска',
      stages: ['search_ready'],
      color: '#16a34a',
    })
  const currentIndex = plan.findIndex((phase) => phase.stages.includes(current))
  return plan.map((phase, index) => {
    const entries = history.filter((entry) => phase.stages.includes(entry.stage))
    const last = entries.at(-1)
    let state = 'pending'
    if (index === currentIndex) {
      state =
        task.status === 'succeeded'
          ? 'done'
          : task.status === 'failed'
            ? 'error'
            : ['cancelled', 'expired'].includes(task.status)
              ? 'stopped'
              : task.status === 'retry_wait'
                ? 'retry'
                : 'current'
      if (phase.key === 'upload' && task.status === 'accepted') state = 'done'
    } else if (last) {
      // Завершённое ожидание в очереди само по себе не означает успешный inference.
      state = last.error_code ? 'error' : index < currentIndex ? 'done' : 'pending'
    } else if (index < currentIndex) state = 'skipped'
    return { ...phase, state }
  })
}

export const phaseStateLabels = {
  pending: 'ожидает',
  current: 'текущий этап',
  done: 'завершён',
  error: 'ошибка',
  stopped: 'остановлен',
  skipped: 'не выполнялся',
  retry: 'ожидает повтора',
}
