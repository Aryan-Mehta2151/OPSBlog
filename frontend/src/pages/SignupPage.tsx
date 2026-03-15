import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { authApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { FiMoon, FiSun } from 'react-icons/fi';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import './Auth.css';

const ORGS = ['Google', 'Amazon', 'Meta'];

export default function SignupPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [organization, setOrganization] = useState(ORGS[0]);
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const savedTheme = localStorage.getItem('theme');
    return savedTheme === 'dark' ? 'dark' : 'light';
  });
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { login } = useAuth();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((currentTheme) => (currentTheme === 'light' ? 'dark' : 'light'));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await authApi.signup({ email, password, organization });
      await login(res.data.access_token, res.data.refresh_token);
      notifySuccess('Account created successfully');
      navigate('/');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Signup failed');
      notifyError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <button
        type="button"
        className="auth-theme-corner-toggle"
        onClick={toggleTheme}
        aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      >
        {theme === 'dark' ? <FiSun /> : <FiMoon />}
      </button>
      <div className="auth-card">
        <h1>SmartBlog</h1>
        <h2>Create Account</h2>
        <form onSubmit={handleSubmit}>
          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <label>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
          />
          <label>Organization</label>
          <select value={organization} onChange={(e) => setOrganization(e.target.value)}>
            {ORGS.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
          <button type="submit" disabled={loading}>
            {loading ? 'Creating account...' : 'Sign Up'}
          </button>
        </form>
        <p className="auth-switch">
          Already have an account? <Link to="/login">Sign In</Link>
        </p>
      </div>
    </div>
  );
}
