import { useState } from 'react';
import { searchApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { FiSearch, FiRefreshCw, FiDatabase } from 'react-icons/fi';
import './Search.css';

interface Source {
  title: string;
  author: string;
  organization: string;
  created_at: string;
  chunk_text: string;
}

export default function SearchPage() {
  const { isAdmin } = useAuth();

  const [question, setQuestion] = useState('');
  const [detailLevel, setDetailLevel] = useState('normal');
  const [answer, setAnswer] = useState('');
  const [sources, setSources] = useState<Source[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');

  // Admin: index + chunks
  const [indexing, setIndexing] = useState(false);
  const [indexMsg, setIndexMsg] = useState('');
  const [chunks, setChunks] = useState<any[]>([]);
  const [showChunks, setShowChunks] = useState(false);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setSearching(true);
    setError('');
    setAnswer('');
    setSources([]);
    try {
      const token = localStorage.getItem('token');
      const base = import.meta.env.VITE_API_BASE_URL ?? '/api';
      const res = await fetch(`${base}/search/query/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ question, detail_level: detailLevel }),
      });
      if (!res.ok) {
        // If 401, try refreshing token
        if (res.status === 401) {
          const refreshToken = localStorage.getItem('refresh_token');
          if (refreshToken) {
            try {
              const refreshRes = await fetch(`${base}/auth/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken }),
              });
              if (refreshRes.ok) {
                const data = await refreshRes.json();
                localStorage.setItem('token', data.access_token);
                localStorage.setItem('refresh_token', data.refresh_token);
                // Retry the search with new token
                setSearching(false);
                handleSearch(e);
                return;
              }
            } catch {}
          }
          localStorage.removeItem('token');
          localStorage.removeItem('refresh_token');
          alert('Your session has expired. Please log in again.');
          window.location.href = '/login';
          return;
        }
        const errData = await res.json().catch(() => null);
        throw new Error(errData?.detail || `HTTP ${res.status}`);
      }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6);
          if (payload === '[DONE]') break;
          try {
            const msg = JSON.parse(payload);
            if (msg.type === 'answer') {
              setAnswer((prev) => prev + msg.content);
            } else if (msg.type === 'sources') {
              setSources(msg.sources);
            }
          } catch {}
        }
      }
    } catch (err: any) {
      setError(err.message || 'Search failed');
    } finally {
      setSearching(false);
    }
  };

  const handleIndex = async () => {
    setIndexing(true);
    setIndexMsg('');
    try {
      const res = await searchApi.index();
      setIndexMsg(res.data.message);
    } catch (err: any) {
      setIndexMsg(err.response?.data?.detail || 'Indexing failed');
    } finally {
      setIndexing(false);
    }
  };

  const handleViewChunks = async () => {
    if (showChunks) {
      setShowChunks(false);
      return;
    }
    try {
      const res = await searchApi.chunks();
      setChunks(res.data);
      setShowChunks(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load chunks');
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>AI Search</h1>
        {isAdmin && (
          <div className="admin-search-actions">
            <button className="btn btn-secondary btn-sm" onClick={handleIndex} disabled={indexing}>
              <FiRefreshCw className={indexing ? 'spin' : ''} />
              {indexing ? 'Indexing...' : 'Re-index'}
            </button>
            <button className="btn btn-secondary btn-sm" onClick={handleViewChunks}>
              <FiDatabase /> {showChunks ? 'Hide Chunks' : 'View Chunks'}
            </button>
          </div>
        )}
      </div>

      {indexMsg && <div className="success-msg">{indexMsg}</div>}
      {error && <div className="error-msg">{error}</div>}

      {/* Search Form */}
      <form className="search-form" onSubmit={handleSearch}>
        <div className="search-input-row">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about your blog content..."
          />
          <select value={detailLevel} onChange={(e) => setDetailLevel(e.target.value)}>
            <option value="brief">Brief</option>
            <option value="normal">Normal</option>
            <option value="detailed">Detailed</option>
          </select>
          <button type="submit" className="btn btn-primary" disabled={searching}>
            <FiSearch /> {searching ? 'Searching...' : 'Search'}
          </button>
        </div>
      </form>

      {/* Answer */}
      {(answer || searching) && (
        <div className="search-answer">
          <h2>Answer</h2>
          <div className="answer-text">
            {answer}
            {searching && <span className="cursor-blink">|</span>}
          </div>

          {sources.length > 0 && (
            <div className="sources-section">
              <h3>Sources ({sources.length})</h3>
              {sources.map((src, i) => (
                <div key={i} className="source-card">
                  <div className="source-title">{src.title}</div>
                  <div className="source-meta">
                    By {src.author} &middot; {src.organization}
                    {src.created_at && <> &middot; {new Date(src.created_at).toLocaleDateString()}</>}
                  </div>
                  <div className="source-chunk">{src.chunk_text}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Chunks (admin) */}
      {showChunks && (
        <div className="chunks-section">
          <h2>Indexed Chunks ({chunks.length})</h2>
          <div className="chunks-list">
            {chunks.map((chunk, i) => (
              <div key={i} className="chunk-card">
                <div className="chunk-id">{chunk.id}</div>
                <div className="chunk-meta">
                  Type: {chunk.metadata?.type || 'text'} &middot; Blog: {chunk.metadata?.title || 'Unknown'}
                </div>
                <div className="chunk-text">{chunk.text?.substring(0, 200)}...</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
