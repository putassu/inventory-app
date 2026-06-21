import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Map, Package, Search, CheckSquare, Settings, LogOut, Calendar } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import './Sidebar.css';

const Sidebar = () => {
  const { logout, user } = useAuth();

  return (
    <aside className="sidebar glass-panel">
      <div className="sidebar-header">
        <h2>AI Inventory</h2>
        <div className="user-info">
          <span className="user-tier">{user?.tier}</span>
          <span className="user-email">{user?.email}</span>
        </div>
      </div>
      
      <nav className="sidebar-nav">
        <NavLink to="/" className={({isActive}) => isActive ? 'nav-link active' : 'nav-link'}>
          <LayoutDashboard size={20} /> Dashboard
        </NavLink>
        <NavLink to="/locations" className={({isActive}) => isActive ? 'nav-link active' : 'nav-link'}>
          <Map size={20} /> Locations
        </NavLink>
        <NavLink to="/items" className={({isActive}) => isActive ? 'nav-link active' : 'nav-link'}>
          <Package size={20} /> Items
        </NavLink>
        <NavLink to="/schedule" className={({isActive}) => isActive ? 'nav-link active' : 'nav-link'}>
          <Calendar size={20} /> Schedule
        </NavLink>
        <NavLink to="/search" className={({isActive}) => isActive ? 'nav-link active' : 'nav-link'}>
          <Search size={20} /> Search
        </NavLink>
        <NavLink to="/tasks" className={({isActive}) => isActive ? 'nav-link active' : 'nav-link'}>
          <CheckSquare size={20} /> Tasks (ML)
        </NavLink>
        <NavLink to="/settings" className={({isActive}) => isActive ? 'nav-link active' : 'nav-link'}>
          <Settings size={20} /> Settings
        </NavLink>
      </nav>

      <div className="sidebar-footer">
        <button className="nav-link logout-btn" onClick={logout}>
          <LogOut size={20} /> Logout
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
