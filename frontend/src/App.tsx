import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';
import BlogListPage from './pages/BlogListPage';
import BlogCreatePage from './pages/BlogCreatePage';
import BlogDetailPage from './pages/BlogDetailPage';
import SearchPage from './pages/SearchPage';
import InvitesPage from './pages/InvitesPage';
import SendInvitePage from './pages/SendInvitePage';
import { ToastContainer } from 'react-toastify';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth();
  if (loading) return <div style={{ padding: '3rem', textAlign: 'center' }}>Loading...</div>;
  if (!token) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function GuestRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth();
  if (loading) return <div style={{ padding: '3rem', textAlign: 'center' }}>Loading...</div>;
  if (token) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<GuestRoute><LoginPage /></GuestRoute>} />
      <Route path="/signup" element={<GuestRoute><SignupPage /></GuestRoute>} />
      <Route path="/" element={<ProtectedRoute><BlogListPage /></ProtectedRoute>} />
      <Route path="/blogs/new" element={<ProtectedRoute><BlogCreatePage /></ProtectedRoute>} />
      <Route path="/blogs/:blogId" element={<ProtectedRoute><BlogDetailPage /></ProtectedRoute>} />
      <Route path="/search" element={<ProtectedRoute><SearchPage /></ProtectedRoute>} />
      <Route path="/invites" element={<ProtectedRoute><InvitesPage /></ProtectedRoute>} />
      <Route path="/invites/send" element={<ProtectedRoute><SendInvitePage /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
        <ToastContainer position="top-right" autoClose={3000} newestOnTop closeOnClick pauseOnHover />
      </AuthProvider>
    </BrowserRouter>
  );
}
