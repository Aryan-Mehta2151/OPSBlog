import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { blogsApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { FiPlus, FiClock, FiEdit } from 'react-icons/fi';
import './Blogs.css';

interface Blog {
  id: string;
  title: string;
  status: string;
  author_id: string;
  created_at: string;
  updated_at: string;
}

export default function BlogListPage() {
  const [blogs, setBlogs] = useState<Blog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const { isAdmin } = useAuth();

  useEffect(() => {
    blogsApi.list()
      .then((res) => setBlogs(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load blogs'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading blogs...</div>;
  if (error) return <div className="error-msg">{error}</div>;

  return (
    <div>
      <div className="page-header">
        <h1>Blog Posts</h1>
        {isAdmin && (
          <Link to="/blogs/new" className="btn btn-primary">
            <FiPlus /> New Blog
          </Link>
        )}
      </div>

      {blogs.length === 0 ? (
        <div className="empty-state">
          <p>No blog posts yet.</p>
          {isAdmin && <p>Create your first blog post to get started.</p>}
        </div>
      ) : (
        <div className="blog-grid">
          {blogs.map((blog) => (
            <Link to={`/blogs/${blog.id}`} key={blog.id} className="blog-card">
              <div className="blog-card-header">
                <h3>{blog.title}</h3>
                <span className={`status-badge ${blog.status}`}>{blog.status}</span>
              </div>
              <div className="blog-card-meta">
                <span><FiClock /> {new Date(blog.created_at).toLocaleDateString()}</span>
                {blog.updated_at && (
                  <span><FiEdit /> {new Date(blog.updated_at).toLocaleDateString()}</span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
