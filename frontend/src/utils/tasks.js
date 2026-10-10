export const pendingItem = (task) =>
  !['succeeded', 'cancelled', 'expired'].includes(task.status) &&
  !task.diagnostics_only &&
  task.purpose !== 'ocr'
