import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { blogsApi } from '../api';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import './Blogs.css';

export default function BlogCreatePage() {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await blogsApi.create({ title, content });
      notifySuccess('Blog created successfully');
      navigate(`/blogs/${res.data.id}`);
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to create blog');
      notifyError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h1>Create Blog Post</h1>
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
