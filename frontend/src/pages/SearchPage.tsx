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
      const res = await searchApi.query(question, detailLevel);
      setAnswer(res.data.answer);
      setSources(res.data.sources);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Search failed');
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
      {answer && (
        <div className="search-answer">
          <h2>Answer</h2>
          <div className="answer-text">{answer}</div>

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
