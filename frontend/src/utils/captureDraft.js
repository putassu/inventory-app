import { onScopeChanged } from '../api/client'

// Передача уже подготовленных фото между способами ввода только в памяти вкладки.
let draft = null
export const getCaptureDraft = () => draft
export const setCaptureDraft = (value) => {
  draft = value
}
export const clearCaptureDraft = () => {
  draft = null
}
onScopeChanged(clearCaptureDraft)
