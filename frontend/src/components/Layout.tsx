import { useAuth } from '../context/AuthContext';
import { Link, useNavigate } from 'react-router-dom';
import { FiLogOut, FiSearch, FiBook, FiUser } from 'react-icons/fi';
import './Layout.css';

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();

  const orgName = user?.organizations?.[0]?.name || '';

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="layout">
      <nav className="navbar">
        <div className="nav-left">
          <Link to="/" className="nav-brand">OpsBlog</Link>
          <span className="nav-org">{orgName}</span>
        </div>
        <div className="nav-links">
          <Link to="/"><FiBook /> Blogs</Link>
          <Link to="/search"><FiSearch /> Search</Link>
        </div>
        <div className="nav-right">
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
