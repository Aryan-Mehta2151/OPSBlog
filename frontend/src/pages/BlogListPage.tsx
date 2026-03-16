import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { blogsApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { FiPlus, FiClock, FiEdit, FiRefreshCw } from 'react-icons/fi';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import './Blogs.css';

interface Blog {
  id: string;
  title: string;
  status: string;
  author_id: string;
  author_username: string | null;
  created_at: string;
  updated_at: string;
}

type BlogViewMode = 'all' | 'my-drafts' | 'my-published';

const BLOG_AUTO_REFRESH_MS = 5000;

type BlogChangesPayload = {
  latest_updated_at?: string | null;
  count?: number;
};

export default function BlogListPage() {
  const [blogs, setBlogs] = useState<Blog[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<BlogViewMode>('all');
  const { isAdmin, user } = useAuth();
  const knownBlogIdsRef = useRef<Set<string>>(new Set());
  const lastChangeSignatureRef = useRef<string | null>(null);

  const toChangeSignature = (payload: BlogChangesPayload) => {
    const latest = payload?.latest_updated_at || 'none';
    const count = typeof payload?.count === 'number' ? payload.count : 0;
    return `${latest}::${count}`;
  };

  const fetchBlogs = useCallback(async (silent = false) => {
    try {
      const res = await blogsApi.list();
      const nextBlogs = Array.isArray(res.data) ? (res.data as Blog[]) : [];

      if (!Array.isArray(res.data)) {
        throw new Error('Unexpected blogs API response. Please restart backend/frontend and try again.');
      }

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

  const checkForBlogUpdates = useCallback(async () => {
    try {
      const res = await blogsApi.changes();
      const payload = res.data as BlogChangesPayload;
      const signature = toChangeSignature(payload);

      if (lastChangeSignatureRef.current === null) {
        lastChangeSignatureRef.current = signature;
        return;
      }

      if (signature !== lastChangeSignatureRef.current) {
        await fetchBlogs(true);
        lastChangeSignatureRef.current = signature;
      }
    } catch {
      // Ignore transient check failures and keep current UI state.
    }
  }, [fetchBlogs]);

  const syncChangesSignature = useCallback(async () => {
    try {
      const res = await blogsApi.changes();
      lastChangeSignatureRef.current = toChangeSignature(res.data as BlogChangesPayload);
    } catch {
      // Ignore signature sync failures.
    }
  }, []);

  useEffect(() => {
    const loadInitialData = async () => {
      await fetchBlogs(false);
      await syncChangesSignature();
    };

    loadInitialData();

    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        checkForBlogUpdates();
      }
    }, BLOG_AUTO_REFRESH_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        checkForBlogUpdates();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchBlogs, checkForBlogUpdates, syncChangesSignature]);

  if (loading) return <div className="loading">Loading blogs...</div>;

  const currentUserId = user?.id;
  const filteredBlogs = blogs.filter((blog) => {
    if (viewMode === 'my-drafts') {
      return blog.author_id === currentUserId && blog.status === 'draft';
    }
    if (viewMode === 'my-published') {
      return blog.author_id === currentUserId && blog.status === 'published';
    }
    return true;
  });

  const getCurrentViewLabel = () => {
    if (viewMode === 'my-drafts') return 'My Drafts';
    if (viewMode === 'my-published') return 'My Published Blogs';
    return 'All Blogs';
  };

  const getCurrentViewHelpText = () => {
    if (viewMode === 'my-drafts') return 'Only your private drafts are shown here.';
    if (viewMode === 'my-published') return 'Only blogs you published are shown here.';
    return 'Published org blogs plus your own drafts.';
  };

  const renderBlogCard = (blog: Blog) => (
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
        {blog.author_username && (
          <span className="blog-card-author">by @{blog.author_username}</span>
        )}
      </div>
    </Link>
  );

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

      {blogs.length > 0 && (
        <div className="blog-filter-row">
          <label htmlFor="blog-view-select">Show</label>
          <select
            id="blog-view-select"
            value={viewMode}
            onChange={(e) => setViewMode(e.target.value as BlogViewMode)}
          >
            <option value="all">All Blogs</option>
            <option value="my-drafts">My Drafts</option>
            <option value="my-published">My Published Blogs</option>
          </select>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={async () => {
              await fetchBlogs(true);
              await syncChangesSignature();
            }}
          >
            <FiRefreshCw /> Refresh
          </button>
          <span className="filter-count">{filteredBlogs.length}</span>
        </div>
      )}

      {blogs.length === 0 ? (
        <div className="empty-state">
          <p>No blogs yet.</p>
          {isAdmin && <p>Create your first blog post to get started.</p>}
        </div>
      ) : (
        <>
          <div className="blog-view-header">
            <h2>{getCurrentViewLabel()}</h2>
            <p>{getCurrentViewHelpText()}</p>
          </div>

          {filteredBlogs.length === 0 ? (
            <div className="empty-state section-empty-state">
              <p>No blogs found in this view.</p>
            </div>
          ) : (
            <div className="blog-grid">
              {filteredBlogs.map(renderBlogCard)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
