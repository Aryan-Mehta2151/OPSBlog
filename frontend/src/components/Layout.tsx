import { useAuth } from '../context/AuthContext';
import { Link, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { FiLogOut, FiSearch, FiBook, FiUser, FiMoon, FiSun, FiBell, FiSend } from 'react-icons/fi';
import { invitesApi } from '../api';
import './Layout.css';

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const savedTheme = localStorage.getItem('theme');
    return savedTheme === 'dark' ? 'dark' : 'light';
  });

  const orgName = user?.organizations?.[0]?.name || '';
  const displayName = user?.username || user?.email || '';
  const [unreadCount, setUnreadCount] = useState(0);

  const fetchUnreadCount = async () => {
    try {
      const res = await invitesApi.unreadCount();
      setUnreadCount(res.data.total || 0);
    } catch {
      // Non-critical
    }
  };

  useEffect(() => {
    if (user) {
      fetchUnreadCount();
      const interval = setInterval(fetchUnreadCount, 15000);
      return () => clearInterval(interval);
    }
  }, [user]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const toggleTheme = () => {
    setTheme((currentTheme) => (currentTheme === 'light' ? 'dark' : 'light'));
  };

  return (
    <div className="layout">
      <nav className="navbar">
        <div className="nav-left">
          <Link to="/" className="nav-brand">SmartBlog</Link>
          <span className="nav-org">{orgName}</span>
        </div>
        <div className="nav-links">
          <Link to="/"><FiBook /> Blogs</Link>
          <Link to="/search"><FiSearch /> Search</Link>
          <Link to="/invites/send"><FiSend /> Invite</Link>
        </div>
        <div className="nav-right">
          <Link to="/invites" className="nav-bell" title="Invites & Notifications">
            <FiBell />
            {unreadCount > 0 && <span className="bell-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>}
          </Link>
          <button className="nav-theme-toggle" onClick={toggleTheme} type="button">
            {theme === 'dark' ? <FiSun /> : <FiMoon />}
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
          <span className="nav-user">
            <FiUser /> {displayName}
            {isAdmin && <span className="badge-admin">Admin</span>}
          </span>
          <button className="nav-logout" onClick={handleLogout}>
            <FiLogOut /> Logout
          </button>
        </div>
      </nav>
      <main className="main-content">
        {children}
      </main>
    </div>
  );
}
