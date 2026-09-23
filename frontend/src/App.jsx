import {
  createBrowserRouter,
  createRoutesFromElements,
  RouterProvider,
  Route,
  Navigate,
  useLocation,
} from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ToastProvider } from './contexts/ToastContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { TaskProvider } from './contexts/TaskContext'
import { NotificationProvider } from './contexts/NotificationContext'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Items } from './pages/Items'
import { ItemDetail } from './pages/ItemDetail'
import { Locations, LocationDetail } from './pages/Locations'
import './index.css'

import { Capture } from './pages/Capture'
import { Tasks, TaskDetail, BatchDetail } from './pages/Tasks'
import { History, OperationDetail } from './pages/History'
import { ReviewInbox } from './pages/ReviewInbox'
import { ReviewForm } from './pages/ReviewForm'
import { Notifications } from './pages/Notifications'
import { Settings } from './pages/Settings'
import { DataPage } from './pages/DataPage'

// Admin imports
import { AdminLayout } from './pages/admin/AdminLayout'
import { AdminSettings } from './pages/admin/AdminSettings'
import { AdminModels } from './pages/admin/AdminModels'
import { AdminQueues } from './pages/admin/AdminQueues'
import { AdminMaintenance } from './pages/admin/AdminMaintenance'
import { TaskTrace } from './pages/admin/TaskTrace'

function ProtectedRoute({ children }) {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          height: '100vh',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-muted)',
        }}
      >
        Загрузка...
      </div>
    )
  }

  if (!user) {
    return (
      <Navigate to="/login" state={{ returnTo: location.pathname + location.search }} replace />
    )
  }

  return children
}

function WorkspaceProviders({ children }) {
  const { user, activeWorkspace } = useAuth()
  if (!user || !activeWorkspace) return children
  return (
    <NotificationProvider key={`${user.id}:${activeWorkspace.id}`}>
      <TaskProvider>{children}</TaskProvider>
    </NotificationProvider>
  )
}

const router = createBrowserRouter(
  createRoutesFromElements(
    <>
      <Route path="/login" element={<Login />} />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <WorkspaceProviders>
              <Layout />
            </WorkspaceProviders>
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/items" replace />} />
        <Route path="items" element={<Items />} />
        <Route path="items/:id" element={<ItemDetail />} />
        <Route path="locations" element={<Locations />} />
        <Route path="locations/:id" element={<LocationDetail />} />
        <Route path="review" element={<ReviewInbox />} />
        <Route path="review/:id" element={<ReviewForm />} />
        <Route path="settings" element={<Settings />} />
        <Route path="data" element={<DataPage />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="capture" element={<Capture />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="tasks/:id" element={<TaskDetail />} />
        <Route path="batches/:id" element={<BatchDetail />} />
        <Route path="history" element={<History />} />
        <Route path="operations/:id" element={<OperationDetail />} />

        <Route path="admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="settings" replace />} />
          <Route path="settings" element={<AdminSettings />} />
          <Route path="models" element={<AdminModels />} />
          <Route path="queues" element={<AdminQueues />} />
          <Route path="maintenance" element={<AdminMaintenance />} />
          <Route path="tasks/:id/trace" element={<TaskTrace />} />
        </Route>
        <Route
          path="*"
          element={
            <div>
              <h1>Страница не найдена</h1>
              <a href="/items">Открыть каталог</a>
            </div>
          }
        />
      </Route>
    </>,
  ),
)

export function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  )
}
