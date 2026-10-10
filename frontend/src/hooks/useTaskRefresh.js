import { useEffect } from 'react'
import { useTasks } from '../contexts/TaskContext'

export function useTaskRefresh(reload) {
  const { activeTasks = [] } = useTasks()
  const version = activeTasks.map((task) => `${task.task_id}:${task.status_version}`).join(',')
  useEffect(() => {
    reload()
  }, [version, reload])
}
