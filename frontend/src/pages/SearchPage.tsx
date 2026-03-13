import { useEffect, useRef, useState } from 'react';
import { handleSessionExpired, searchApi } from '../api';
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

interface ChatTurn {
  id: string;
  question: string;
  answer: string;
  sources: Source[];
}

export default function SearchPage() {
  const { isAdmin } = useAuth();

  const [question, setQuestion] = useState('');
  const [detailLevel, setDetailLevel] = useState('normal');
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');

  // Admin: index + chunks
  const [indexing, setIndexing] = useState(false);
  const [indexMsg, setIndexMsg] = useState('');
  const [chunks, setChunks] = useState<any[]>([]);
  const [showChunks, setShowChunks] = useState(false);
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Load chat history from sessionStorage on mount
  useEffect(() => {
    const savedChat = sessionStorage.getItem('searchChat');
    const savedExpandedSources = sessionStorage.getItem('expandedSources');

    if (savedChat) {
      try {
        setChat(JSON.parse(savedChat));
      } catch (e) {
        console.error('Failed to parse saved chat:', e);
      }
    }

    if (savedExpandedSources) {
      try {
        setExpandedSources(JSON.parse(savedExpandedSources));
      } catch (e) {
        console.error('Failed to parse saved expanded sources:', e);
      }
    }
  }, []);

  // Save chat history to sessionStorage whenever it changes
  useEffect(() => {
    if (chat.length > 0) {
      sessionStorage.setItem('searchChat', JSON.stringify(chat));
    }
  }, [chat]);

  // Save expanded sources to sessionStorage whenever it changes
  useEffect(() => {
    if (Object.keys(expandedSources).length > 0) {
      sessionStorage.setItem('expandedSources', JSON.stringify(expandedSources));
    }
  }, [expandedSources]);

  const updateTurn = (turnId: string, updater: (turn: ChatTurn) => ChatTurn) => {
    setChat((prev) => prev.map((turn) => (turn.id === turnId ? updater(turn) : turn)));
  };

  const refreshAccessToken = async (base: string): Promise<string | null> => {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) return null;

    try {
      const refreshRes = await fetch(`${base}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!refreshRes.ok) return null;

      const data = await refreshRes.json();
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      return data.access_token;
    } catch {
      return null;
    }
  };

  const streamSearch = async (query: string, turnId: string, token: string | null, hasRetried = false): Promise<void> => {
    const base = import.meta.env.VITE_API_BASE_URL ?? '/api';
    const res = await fetch(`${base}/search/query/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question: query, detail_level: detailLevel }),
    });

    if (!res.ok) {
      if (res.status === 401 && !hasRetried) {
        const newToken = await refreshAccessToken(base);
        if (newToken) {
          return streamSearch(query, turnId, newToken, true);
        }
        handleSessionExpired();
        return;
      }

      const errData = await res.json().catch(() => null);
      throw new Error(errData?.detail || `HTTP ${res.status}`);
    }

    const reader = res.body?.getReader();
    if (!reader) {
      throw new Error('No stream received from server');
    }

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
        if (payload === '[DONE]') continue;

        try {
          const msg = JSON.parse(payload);
          if (msg.type === 'answer') {
            updateTurn(turnId, (turn) => ({ ...turn, answer: turn.answer + msg.content }));
          } else if (msg.type === 'sources') {
            updateTurn(turnId, (turn) => ({ ...turn, sources: msg.sources || [] }));
          }
        } catch {
          // Ignore non-JSON SSE messages
        }
      }
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const query = question.trim();
    if (!query) return;

    const turnId = `${Date.now()}`;
    setChat((prev) => [...prev, { id: turnId, question: query, answer: '', sources: [] }]);
    setActiveTurnId(turnId);
    setSearching(true);
    setError('');
    setQuestion('');

    try {
      const token = localStorage.getItem('token');
      await streamSearch(query, turnId, token);
    } catch (err: any) {
      setError(err.message || 'Search failed');
    } finally {
      setSearching(false);
      setActiveTurnId(null);
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

  const toggleSources = (turnId: string) => {
    setExpandedSources((prev) => ({
      ...prev,
      [turnId]: !prev[turnId],
    }));
  };

  const clearChatHistory = () => {
    setChat([]);
    setExpandedSources({});
    sessionStorage.removeItem('searchChat');
    sessionStorage.removeItem('expandedSources');
  };

  return (
    <div className="search-page">
      <div className="search-toolbar">
        <div className="page-header search-toolbar-header">
          <h1>AI Search</h1>
          {isAdmin && (
            <div className="admin-search-actions">
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleIndex} disabled={indexing}>
                <FiRefreshCw className={indexing ? 'spin' : ''} />
                {indexing ? 'Indexing...' : 'Re-index'}
              </button>
              <button type="button" className="btn btn-secondary btn-sm" onClick={handleViewChunks}>
                <FiDatabase /> {showChunks ? 'Hide Chunks' : 'View Chunks'}
              </button>
            </div>
          )}
        </div>

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
            {chat.length > 0 && (
              <button type="button" className="btn btn-secondary" onClick={clearChatHistory}>
                Clear Chat
              </button>
            )}
          </div>
        </form>

        {indexMsg && <div className="success-msg">{indexMsg}</div>}
        {error && <div className="error-msg">{error}</div>}
      </div>

      {/* Chunks (admin) */}
      {showChunks ? (
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
      ) : (
        chat.length > 0 && (
          <div className="search-chat">
            {chat.map((turn) => (
              <div key={turn.id} className="search-turn">
                <div className="search-question-card">
                  <h3>You asked</h3>
                  <div className="answer-text">{turn.question}</div>
                </div>

                <div className="search-answer">
                  <h2>Answer</h2>
                  <div className="answer-text">
                    {turn.answer}
                    {searching && activeTurnId === turn.id && <span className="cursor-blink">|</span>}
                  </div>

                  {turn.sources.length > 0 && (
                    <div className="sources-toggle-block">
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => toggleSources(turn.id)}>
                        <FiDatabase /> {expandedSources[turn.id] ? 'Hide Sources' : `Show Sources (${turn.sources.length})`}
                      </button>

                      {expandedSources[turn.id] && (
                        <div className="sources-section">
                          <h3>Sources ({turn.sources.length})</h3>
                          {turn.sources.map((src, i) => (
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
                </div>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
        )
      )}
    </div>
  );
}
