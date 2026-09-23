import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { allPages } from '../api/client'
import { pollTasksStatus } from '../api/tasks'
import { onConfirmation } from '../api/confirmations'

const TaskContext = createContext({})
export const terminalTask = (status) =>
  ['succeeded', 'failed', 'cancelled', 'expired'].includes(status)
export function TaskProvider({ children }) {
  const [activeTasks, setTasks] = useState([])
  const [error, setError] = useState('')
  const tasksRef = useRef([])
  const merge = useCallback((changed) => {
    const rows = new Map(tasksRef.current.map((task) => [task.task_id, task]))
    for (const task of changed) {
      if ((rows.get(task.task_id)?.status_version || 0) <= task.status_version)
        rows.set(task.task_id, task)
    }
    tasksRef.current = [...rows.values()]
    setTasks(tasksRef.current)
  }, [])
  const addTask = useCallback((task) => merge([task]), [merge])
  const refreshTasks = useCallback(async () => {
    const rows = await allPages('/tasks')
    merge(rows)
  }, [merge])
  useEffect(() => {
    let active = true
    let timer
    const controller = new AbortController()
    const unsubscribe = onConfirmation((receipt) => {
      if (active && receipt.status === 'applied') refreshTasks().catch(() => {})
    })
    async function poll() {
      try {
        if (!document.hidden) {
          const pending = tasksRef.current.filter((task) => !terminalTask(task.status))
          for (let offset = 0; active && offset < pending.length; offset += 100) {
            const result = await pollTasksStatus(
              pending
                .slice(offset, offset + 100)
                .map((task) => ({ task_id: task.task_id, status_version: task.status_version })),
              controller.signal,
            )
            if (active) merge(result.changed)
          }
          if (active) setError('')
        }
      } catch (cause) {
        if (active && cause.name !== 'AbortError') setError(cause.message)
      }
      if (active) timer = setTimeout(poll, 3000)
    }
    allPages('/tasks', { signal: controller.signal })
      .then((rows) => {
        if (active) merge(rows)
      })
      .catch((cause) => {
        if (active && cause.name !== 'AbortError') setError(cause.message)
      })
      .finally(() => {
        if (active) void poll()
      })
    return () => {
      active = false
      clearTimeout(timer)
      controller.abort()
      unsubscribe()
    }
  }, [merge, refreshTasks])
  return (
    <TaskContext.Provider value={{ activeTasks, addTask, refreshTasks, error }}>
      {children}
    </TaskContext.Provider>
  )
}
export const useTasks = () => useContext(TaskContext)
