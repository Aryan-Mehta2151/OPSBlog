import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { blogsApi } from '../api';
import './Blogs.css';

export default function BlogCreatePage() {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      const res = await blogsApi.create({ title, content });
      navigate(`/blogs/${res.data.id}`);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create blog');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h1>Create Blog Post</h1>
      {error && <div className="error-msg">{error}</div>}
      <form className="blog-form" onSubmit={handleSubmit}>
        <label>Title</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Enter blog title"
          required
        />
        <label>Content</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Write your blog content..."
          rows={12}
        />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={() => navigate('/')}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Creating...' : 'Create Blog'}
          </button>
        </div>
      </form>
    </div>
  );
}
