import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Locations from './pages/Locations';
import Items from './pages/Items';
import Search from './pages/Search';
import Tasks from './pages/Tasks';
import Settings from './pages/Settings';
import Schedule from './pages/Schedule';
import './styles/design-system.css';

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="locations" element={<Locations />} />
            <Route path="items" element={<Items />} />
            <Route path="search" element={<Search />} />
            <Route path="tasks" element={<Tasks />} />
            <Route path="schedule" element={<Schedule />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
