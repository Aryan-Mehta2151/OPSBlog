import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { blogsApi } from '../api';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import './Blogs.css';

export default function BlogCreatePage() {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [detailLevel, setDetailLevel] = useState('normal');
  const [outputMode, setOutputMode] = useState('paraphrase');
  const [importing, setImporting] = useState(false);
  const [saving, setSaving] = useState(false);
  const navigate = useNavigate();

  const handleImportFromUrl = async () => {
    const cleanUrl = sourceUrl.trim();
    if (!cleanUrl) {
      notifyError('Please enter a website/blog URL first');
      return;
    }

    setImporting(true);
    try {
      const res = await blogsApi.importFromUrl({
        url: cleanUrl,
        detail_level: detailLevel,
        output_mode: outputMode,
      });
      setTitle(res.data.title || 'Imported draft');
      setContent(res.data.content || '');
      notifySuccess('Draft generated from URL. Review and create your blog.');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to import draft from URL');
      notifyError(msg);
    } finally {
      setImporting(false);
    }
  };

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
      <div className="import-url-panel">
        <h3>Import Draft From External URL</h3>
        <p>Paste a public blog/article URL and auto-generate a draft.</p>
        <div className="import-url-controls">
          <input
            type="url"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://example.com/blog/article"
          />
          <select value={outputMode} onChange={(e) => setOutputMode(e.target.value)}>
            <option value="summary">Summary</option>
            <option value="paraphrase">Paraphrased</option>
            <option value="exact">Exact text</option>
          </select>
         
          <button
            type="button"
            className="btn btn-secondary"
            disabled={importing}
            onClick={handleImportFromUrl}
          >
            {importing ? 'Fetching...' : 'Fetch'}
          </button>
        </div>
      </div>

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
