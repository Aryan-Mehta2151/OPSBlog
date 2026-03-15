import { useAuth } from '../context/AuthContext';
import { Link, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { FiLogOut, FiSearch, FiBook, FiUser, FiMoon, FiSun } from 'react-icons/fi';
import './Layout.css';

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const savedTheme = localStorage.getItem('theme');
    return savedTheme === 'dark' ? 'dark' : 'light';
  });

  const orgName = user?.organizations?.[0]?.name || '';

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
        </div>
        <div className="nav-right">
          <button className="nav-theme-toggle" onClick={toggleTheme} type="button">
            {theme === 'dark' ? <FiSun /> : <FiMoon />}
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
          <span className="nav-user">
            <FiUser /> {user?.email}
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
