import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { blogsApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { FiPlus, FiClock, FiEdit } from 'react-icons/fi';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import './Blogs.css';

const BLOG_REFRESH_INTERVAL_MS = 4000;

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
  const { isAdmin } = useAuth();
  const knownBlogIdsRef = useRef<Set<string>>(new Set());

  const fetchBlogs = useCallback(async (silent = false) => {
    try {
      const res = await blogsApi.list();
      const nextBlogs = res.data as Blog[];

      if (silent && knownBlogIdsRef.current.size > 0) {
        const newBlogs = nextBlogs.filter((blog) => !knownBlogIdsRef.current.has(blog.id));
        if (newBlogs.length > 0) {
          notifySuccess(
            newBlogs.length === 1
              ? '1 new blog is now available.'
              : `${newBlogs.length} new blogs are now available.`
          );
        }
      }

      knownBlogIdsRef.current = new Set(nextBlogs.map((blog) => blog.id));
      setBlogs(nextBlogs);
    } catch (err: any) {
      if (!silent) {
        const msg = getApiErrorMessage(err, 'Failed to load blogs');
        notifyError(msg);
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchBlogs(false);

    const intervalId = window.setInterval(() => {
      fetchBlogs(true);
    }, BLOG_REFRESH_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchBlogs(true);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchBlogs]);

  if (loading) return <div className="loading">Loading blogs...</div>;

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
