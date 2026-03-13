import { useEffect, useMemo, useRef, useState } from 'react';
import { handleSessionExpired, searchApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { FiSearch, FiRefreshCw, FiDatabase, FiPlus, FiTrash2 } from 'react-icons/fi';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
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

interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: ChatTurn[];
}

interface StreamResult {
  answer: string;
  sources: Source[];
}

const buildConversationTitle = (query: string) => {
  const normalized = query.trim().replace(/\s+/g, ' ');
  if (normalized.length <= 40) {
    return normalized;
  }
  return `${normalized.slice(0, 40).trim()}...`;
};

export default function SearchPage() {
  const { isAdmin, user, loading } = useAuth();

  const [question, setQuestion] = useState('');
  const [detailLevel, setDetailLevel] = useState('normal');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [error, setError] = useState('');

  const [indexing, setIndexing] = useState(false);
  const [indexMsg, setIndexMsg] = useState('');
  const [chunks, setChunks] = useState<any[]>([]);
  const [showChunks, setShowChunks] = useState(false);
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const conversationsRef = useRef<Conversation[]>([]);

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    if (loading) {
      return;
    }

    if (!user) {
      setConversations([]);
      setActiveConversationId(null);
      setExpandedSources({});
      return;
    }

    const loadConversations = async () => {
      setLoadingConversations(true);
      try {
        const res = await searchApi.listConversations();
        const loadedConversations = (res.data ?? []).map((conversation: any) => ({
          id: conversation.id,
          title: conversation.title,
          createdAt: conversation.created_at,
          updatedAt: conversation.updated_at,
          turns: conversation.turns ?? [],
        }));
        setConversations(loadedConversations);
        setActiveConversationId((prev) => {
          if (prev && loadedConversations.some((conversation: Conversation) => conversation.id === prev)) {
            return prev;
          }
          return loadedConversations[0]?.id ?? null;
        });
      } catch (err: any) {
        const msg = getApiErrorMessage(err, 'Failed to load saved chats');
        setError(msg);
        notifyError(msg);
      } finally {
        setLoadingConversations(false);
      }
    };

    loadConversations();
  }, [loading, user]);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) ?? null,
    [activeConversationId, conversations]
  );

  const updateConversation = (conversationId: string, updater: (conversation: Conversation) => Conversation) => {
    setConversations((prev) =>
      prev.map((conversation) =>
        conversation.id === conversationId ? updater(conversation) : conversation
      )
    );
  };

  const upsertConversationLocally = (nextConversation: Conversation, moveToTop = true) => {
    setConversations((prev) => {
      const remaining = prev.filter((conversation) => conversation.id !== nextConversation.id);
      return moveToTop ? [nextConversation, ...remaining] : [...remaining, nextConversation];
    });
  };

  const updateTurn = (
    conversationId: string,
    turnId: string,
    updater: (turn: ChatTurn) => ChatTurn
  ) => {
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: new Date().toISOString(),
      turns: conversation.turns.map((turn) => (turn.id === turnId ? updater(turn) : turn)),
    }));
  };

  const persistConversation = async (conversation: Conversation) => {
    const payload = {
      title: conversation.title,
      turns: conversation.turns.map((turn) => ({
        id: turn.id,
        question: turn.question,
        answer: turn.answer,
        sources: turn.sources,
      })),
    };
    const res = await searchApi.updateConversation(conversation.id, payload);
    const savedConversation: Conversation = {
      id: res.data.id,
      title: res.data.title,
      createdAt: res.data.created_at,
      updatedAt: res.data.updated_at,
      turns: res.data.turns ?? [],
    };
    upsertConversationLocally(savedConversation, true);
    return savedConversation;
  };

  const createConversation = async () => {
    const res = await searchApi.createConversation({ title: 'New chat' });
    const nextConversation: Conversation = {
      id: res.data.id,
      title: res.data.title,
      createdAt: res.data.created_at,
      updatedAt: res.data.updated_at,
      turns: res.data.turns ?? [],
    };
    upsertConversationLocally(nextConversation, true);
    setActiveConversationId(nextConversation.id);
    setShowChunks(false);
    setError('');
    return nextConversation;
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

  const streamSearch = async (
    query: string,
    conversationId: string,
    turnId: string,
    token: string | null,
    hasRetried = false
  ): Promise<StreamResult> => {
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
          return streamSearch(query, conversationId, turnId, newToken, true);
        }
        handleSessionExpired();
        return { answer: '', sources: [] };
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
    let fullAnswer = '';
    let finalSources: Source[] = [];

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
            fullAnswer += msg.content || '';
            updateTurn(conversationId, turnId, (turn) => ({ ...turn, answer: turn.answer + msg.content }));
          } else if (msg.type === 'sources') {
            finalSources = msg.sources || [];
            updateTurn(conversationId, turnId, (turn) => ({ ...turn, sources: msg.sources || [] }));
          }
        } catch {
          // Ignore non-JSON SSE messages
        }
      }
    }

    return { answer: fullAnswer, sources: finalSources };
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const query = question.trim();
    if (!query) return;

    let targetConversation = activeConversation;
    if (!targetConversation) {
      try {
        targetConversation = await createConversation();
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Failed to create a new chat');
        return;
      }
    }

    const conversationId = targetConversation.id;
    const turnId = `${Date.now()}`;
    const turn: ChatTurn = { id: turnId, question: query, answer: '', sources: [] };
    const updatedConversation: Conversation = {
      ...targetConversation,
      title: targetConversation.turns.length === 0 ? buildConversationTitle(query) : targetConversation.title,
      updatedAt: new Date().toISOString(),
      turns: [turn, ...targetConversation.turns],
    };

    upsertConversationLocally(updatedConversation, true);

    setActiveConversationId(conversationId);
    setActiveTurnId(turnId);
    setSearching(true);
    setShowChunks(false);
    setError('');
    setQuestion('');

    try {
      await persistConversation(updatedConversation);
      const token = localStorage.getItem('token');
      const streamResult = await streamSearch(query, conversationId, turnId, token);
      const finalizedConversation: Conversation = {
        ...updatedConversation,
        updatedAt: new Date().toISOString(),
        turns: updatedConversation.turns.map((existingTurn) =>
          existingTurn.id === turnId
            ? {
                ...existingTurn,
                answer: streamResult.answer,
                sources: streamResult.sources,
              }
            : existingTurn
        ),
      };
      upsertConversationLocally(finalizedConversation, true);
      await persistConversation(finalizedConversation);
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Search failed');
      setError(msg);
      notifyError(msg);
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
      notifySuccess(res.data.message || 'Re-index completed');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Indexing failed');
      setIndexMsg(msg);
      notifyError(msg);
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
      const msg = getApiErrorMessage(err, 'Failed to load chunks');
      setError(msg);
      notifyError(msg);
    }
  };

  const toggleSources = (turnId: string) => {
    setExpandedSources((prev) => ({
      ...prev,
      [turnId]: !prev[turnId],
    }));
  };

  const handleNewChat = async () => {
    try {
      await createConversation();
      setQuestion('');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to create a new chat');
      setError(msg);
      notifyError(msg);
    }
  };

  const handleDeleteConversation = async (conversationId: string) => {
    try {
      await searchApi.deleteConversation(conversationId);
      setConversations((prev) => prev.filter((conversation) => conversation.id !== conversationId));
      setExpandedSources((prev) => {
        const next = { ...prev };
        const conversation = conversationsRef.current.find((item) => item.id === conversationId);
        for (const turn of conversation?.turns ?? []) {
          delete next[turn.id];
        }
        return next;
      });
      setActiveConversationId((prev) => {
        if (prev !== conversationId) {
          return prev;
        }
        const remaining = conversationsRef.current.filter((conversation) => conversation.id !== conversationId);
        return remaining[0]?.id ?? null;
      });
      setError('');
      notifySuccess('Chat deleted');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to delete chat');
      setError(msg);
      notifyError(msg);
    }
  };

  const activeTurns = activeConversation?.turns ?? [];

  return (
    <div className="search-page">
      <aside className="search-sidebar">
        <button type="button" className="btn btn-primary search-new-chat" onClick={handleNewChat} disabled={searching}>
          <FiPlus /> New Chat
        </button>

        <div className="search-conversation-list">
          {loadingConversations ? (
            <div className="search-empty-state">Loading chats...</div>
          ) : conversations.length === 0 ? (
            <div className="search-empty-state">Your saved chats for this session will appear here.</div>
          ) : (
            conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={`search-conversation-item ${conversation.id === activeConversationId ? 'active' : ''}`}
              >
                <button
                  type="button"
                  className="search-conversation-select"
                  onClick={() => {
                    setActiveConversationId(conversation.id);
                    setShowChunks(false);
                    setError('');
                  }}
                >
                  <span className="search-conversation-title">{conversation.title}</span>
                  <span className="search-conversation-meta">
                    {conversation.turns.length === 0 ? 'No messages yet' : `${conversation.turns.length} message${conversation.turns.length === 1 ? '' : 's'}`}
                  </span>
                </button>
                <button
                  type="button"
                  className="search-conversation-delete"
                  onClick={() => handleDeleteConversation(conversation.id)}
                  aria-label={`Delete ${conversation.title}`}
                >
                  <FiTrash2 />
                </button>
              </div>
            ))
          )}
        </div>
      </aside>

      <div className="search-main">
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
            </div>
          </form>

          {indexMsg && <div className="success-msg">{indexMsg}</div>}
        </div>

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
        ) : activeConversation ? (
          activeTurns.length > 0 ? (
            <div className="search-chat">
              {activeTurns.map((turn) => (
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
            </div>
          ) : (
            <div className="search-placeholder">
              <h2>{activeConversation.title}</h2>
              <p>Start asking questions to build this chat. New messages will appear at the top.</p>
            </div>
          )
        ) : (
          <div className="search-placeholder">
            <h2>No active chat</h2>
            <p>Create a new chat and ask your first question.</p>
          </div>
        )}
      </div>
    </div>
  );
}
