import { Link } from 'react-router-dom'
import { useTasks } from '../contexts/TaskContext'
import { Thumbnail } from './ui/Thumbnail'
import { label } from '../utils/labels'
import { pendingItem } from '../utils/tasks'
import { StageRing } from './StageRing'
export function PendingItems({ locationIds, query = '' }) {
  const { activeTasks = [] } = useTasks()
  const tasks = activeTasks.filter(
    (task) =>
      pendingItem(task) &&
      !task.context?.item_id &&
      !task.catalog_item_ids?.length &&
      (!locationIds || locationIds.has(task.context?.location_id)) &&
      (!query || task.title?.toLocaleLowerCase().includes(query.toLocaleLowerCase())),
  )
  if (!tasks.length) return null
  return (
    <div className="page-stack pending-items" aria-label="Вещи в обработке">
      {tasks.map((task) => (
        <Link
          className={`card item-row processing-card processing-${task.status}`}
          key={task.task_id}
          to={task.proposal_id ? `/review/${task.proposal_id}` : `/tasks/${task.task_id}`}
        >
          <Thumbnail mediaId={task.preview_media_id} size={56} alt="Фото добавляемой вещи" />
          <StageRing task={task} />
          <div className="item-summary">
            <strong>{task.title || 'Новая вещь'}</strong>
            <p>
              <span className={`status-badge status-${task.status}`}>{label(task.status)}</span>
            </p>
            <small>{label(task.stage)}</small>
            <small>
              {task.status === 'waiting_for_review'
                ? 'Проверьте распознанные сведения'
                : task.status === 'failed'
                  ? 'Откройте, чтобы заполнить вручную'
                  : 'Можно продолжать работу — сведения появятся здесь'}
            </small>
          </div>
        </Link>
      ))}
    </div>
  )
}
