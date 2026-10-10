import { Link } from 'react-router-dom'
import { reviewLabels } from '../utils/labels'

export function ItemReviewStatus({ item, link = true }) {
  const status = item.review_status || 'confirmed'
  const text = reviewLabels[status]
  const className = `status-badge item-review-${status}`
  const title = {
    processing: 'Карточка уже в каталоге. Распознанные сведения появятся автоматически.',
    unconfirmed: 'Вещь участвует в поиске и напоминаниях. Данные ещё не проверены человеком.',
    error: 'Карточка сохранена. Исправьте сведения вручную или повторите распознавание.',
    confirmed: 'Данные проверены пользователем.',
  }[status]
  const path = item.review_proposal_id
    ? `/review/${item.review_proposal_id}`
    : item.review_task_id
      ? `/tasks/${item.review_task_id}`
      : null
  return link && path && status !== 'confirmed' ? (
    <Link className={className} title={title} to={path}>
      {text}
    </Link>
  ) : (
    <span className={className} title={title}>
      {text}
    </span>
  )
}
