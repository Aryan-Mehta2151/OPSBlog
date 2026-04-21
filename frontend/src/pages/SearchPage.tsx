import { useEffect, useMemo, useRef, useState } from 'react';
import { documentsApi, handleSessionExpired, searchApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { FiSearch, FiRefreshCw, FiDatabase, FiPlus, FiTrash2, FiDownload } from 'react-icons/fi';
import { jsPDF } from 'jspdf';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import './Search.css';
import './HomePage.css';

interface Source {
  title: string;
  author: string;
  organization: string;
  created_at: string;
  chunk_text: string;
  type?: string;
  blog_id?: string;
  image_id?: string;
  filename?: string;
  context_image_index?: number;
  source_pdf_filename?: string;
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

interface InterleavedImageSource {
  source: Source;
  blogId: string | null;
  imageId: string | null;
  key: string;
}

const buildConversationTitle = (query: string) => {
  const normalized = query.trim().replace(/\s+/g, ' ');
  if (normalized.length <= 40) {
    return normalized;
  }
  return `${normalized.slice(0, 40).trim()}...`;
};

const normalizeAnswerText = (text: string) => {
  const raw = text || '';
  return raw
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/__(.*?)__/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/\r\n/g, '\n');
};

function SourceImagePreview({
  source,
  blogId,
  imageId,
  onOpen,
}: {
  source: Source;
  blogId: string | null;
  imageId: string | null;
  onOpen: (blogId: string, imageId: string, label: string) => void;
}) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [loadingImg, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isImageSource = source.type === 'image' || source.type === 'pdf_embedded_image';

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;

    const loadPreview = async () => {
      if (!isImageSource || !blogId || !imageId) return;
      setLoading(true);
      setError('');
      try {
        const res = await documentsApi.viewImage(blogId, imageId);
        objectUrl = URL.createObjectURL(res.data);
        if (active) {
          setImageUrl(objectUrl);
        }
      } catch {
        if (active) {
          setError('Failed to load image preview');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    loadPreview();

    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [isImageSource, blogId, imageId]);

  if (!isImageSource || !blogId || !imageId) return null;

  return (
    <div className="source-image-wrap">
      <div className="source-image-label">
        {source.type === 'pdf_embedded_image' ? 'Image from PDF' : 'Image match'}
        {source.source_pdf_filename ? ` • ${source.source_pdf_filename}` : ''}
      </div>
      {loadingImg && <div className="source-image-loading">Loading image...</div>}
      {error && <div className="source-image-error">{error}</div>}
      {!loadingImg && !error && imageUrl && (
        <button
          type="button"
          className="source-image-button"
          onClick={() => onOpen(blogId, imageId, source.filename || source.title)}
        >
          <img src={imageUrl} alt={source.filename || source.title} className="source-image-inline" />
        </button>
      )}
    </div>
  );
}

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
  const [imagePreview, setImagePreview] = useState<{ url: string; name: string } | null>(null);
  const conversationsRef = useRef<Conversation[]>([]);
  const chatTopRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    return () => {
      if (imagePreview?.url) {
        URL.revokeObjectURL(imagePreview.url);
      }
    };
  }, [imagePreview]);

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

  const resolveSourceImageRef = (source: Source): { blogId: string | null; imageId: string | null } => {
    if (source.blog_id && source.image_id) {
      return { blogId: source.blog_id, imageId: source.image_id };
    }
    return { blogId: source.blog_id || null, imageId: source.image_id || null };
  };

  const getInterleavedImageSources = (sources: Source[]): InterleavedImageSource[] => {
    const imageSources = sources.filter(
      (src) => src.type === 'image' || src.type === 'pdf_embedded_image',
    );
    const seen = new Set<string>();
    const collected: InterleavedImageSource[] = [];

    for (const src of imageSources) {
      const { blogId, imageId } = resolveSourceImageRef(src);
      if (!blogId || !imageId) continue;

      const key = `${blogId}|${imageId}|${src.filename || src.title}`;
      if (seen.has(key)) continue;
      seen.add(key);

      collected.push({
        source: src,
        blogId,
        imageId,
        key,
      });
    }
    return collected;
  };

  const handleOpenSourceImage = async (blogId: string, imageId: string, label: string) => {
    try {
      const res = await documentsApi.viewImage(blogId, imageId);
      const url = URL.createObjectURL(res.data);
      setImagePreview((prev) => {
        if (prev?.url) URL.revokeObjectURL(prev.url);
        return {
          url,
          name: label,
        };
      });
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to open image source'));
    }
  };

  const streamSearch = async (
    query: string,
    conversationId: string,
    turnId: string,
    token: string | null,
    hasRetried = false
  ): Promise<StreamResult> => {
    const base = (import.meta.env.VITE_API_BASE_URL || '/api').trim() || '/api';

    // Build conversation history from recent turns (close context)
    const conv = conversations.find(c => c.id === conversationId);
    const previousTurns = (conv?.turns || [])
      .filter(t => t.id !== turnId && t.answer)
      .slice(0, 10);
    const conversationHistory = [...previousTurns].reverse().map(t => ({
      question: t.question,
      answer: t.answer,
    }));

    // Collect image keys already shown (within last 20 turns) for dedup
    const IMAGE_DEDUP_WINDOW = 20;
    const shownImageIds: string[] = [];
    const recentForDedup = (conv?.turns || [])
      .filter(t => t.id !== turnId && t.sources?.length)
      .slice(0, IMAGE_DEDUP_WINDOW);
    for (const t of recentForDedup) {
      for (const s of t.sources) {
        if (s.type === 'image' || s.type === 'pdf_embedded_image') {
          const key = [s.type || '', s.blog_id || '', s.image_id || '', s.filename || ''].join('|');
          if (!shownImageIds.includes(key)) shownImageIds.push(key);
        }
      }
    }

    const res = await fetch(`${base}/search/query/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        question: query,
        detail_level: detailLevel,
        conversation_history: conversationHistory,
        shown_image_ids: shownImageIds,
      }),
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

    // Scroll so the newest question card sits just below sticky headers.
    setTimeout(() => {
      const el = chatTopRef.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top + window.scrollY - 88;
      window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    }, 50);

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

  const handleDownloadAnswerPdf = async (turn: ChatTurn, index: number) => {
    try {
      const doc = new jsPDF({ unit: 'pt', format: 'a4' });
      const pageWidth = doc.internal.pageSize.getWidth();
      const pageHeight = doc.internal.pageSize.getHeight();
      const margin = 40;
      const contentWidth = pageWidth - margin * 2;
      let y = margin;

      const writeParagraph = (text: string, fontSize = 11, bold = false) => {
        doc.setFont('helvetica', bold ? 'bold' : 'normal');
        doc.setFontSize(fontSize);
        const lines = doc.splitTextToSize(text || '', contentWidth);
        for (const line of lines) {
          if (y > pageHeight - margin) {
            doc.addPage();
            y = margin;
          }
          doc.text(line, margin, y);
          y += fontSize + 4;
        }
      };

      const writeAnswerText = (text: string) => {
        const paragraphs = text
          .split(/\n\s*\n/)
          .map((p) => p.trim())
          .filter(Boolean);
        if (paragraphs.length === 0) {
          return;
        }
        paragraphs.forEach((p) => {
          writeParagraph(p, 11, false);
          y += 4;
        });
      };

      const normalizedAnswer = normalizeAnswerText(turn.answer || '');

      const blobToDataUrl = (blob: Blob) =>
        new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onloadend = () => resolve(String(reader.result || ''));
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });

      const loadImage = (src: string) =>
        new Promise<HTMLImageElement>((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = src;
        });

      writeParagraph('Answer', 14, true);
      y += 8;

      const imageSources = turn.sources.filter(
        (src) => src.type === 'image' || src.type === 'pdf_embedded_image'
      );
      const imageByContextIndex = new Map<number, Source>();
      for (const src of imageSources) {
        if (typeof src.context_image_index === 'number') {
          imageByContextIndex.set(src.context_image_index, src);
        }
      }

      const drawInlineImage = async (src: Source, displayNum: number) => {
        if (!src.blog_id || !src.image_id) {
          return;
        }
        const res = await documentsApi.viewImage(src.blog_id, src.image_id);
        const blob = res.data as Blob;
        const dataUrl = await blobToDataUrl(blob);
        const image = await loadImage(dataUrl);

        const maxWidth = contentWidth;
        const maxHeight = 240;
        const scale = Math.min(maxWidth / image.width, maxHeight / image.height, 1);
        const drawWidth = image.width * scale;
        const drawHeight = image.height * scale;

        if (y + drawHeight + 28 > pageHeight - margin) {
          doc.addPage();
          y = margin;
        }

        const format = (blob.type || '').toLowerCase().includes('png') ? 'PNG' : 'JPEG';
        doc.addImage(dataUrl, format, margin, y, drawWidth, drawHeight);
        y += drawHeight + 6;
        writeParagraph(`Image ${displayNum}`, 9, true);
        y += 6;
      };

      const IMAGE_MARKER = /\[Image\s+(\d+)(?:\s*[—–\-][^\]]*)?\]/gi;
      const segments: Array<{ text: string; imageNum?: number }> = [];
      let lastIndex = 0;
      let match: RegExpExecArray | null;
      IMAGE_MARKER.lastIndex = 0;
      while ((match = IMAGE_MARKER.exec(normalizedAnswer)) !== null) {
        if (match.index > lastIndex) {
          segments.push({ text: normalizedAnswer.slice(lastIndex, match.index) });
        }
        segments.push({ text: '', imageNum: parseInt(match[1], 10) });
        lastIndex = match.index + match[0].length;
      }
      if (lastIndex < normalizedAnswer.length) {
        segments.push({ text: normalizedAnswer.slice(lastIndex) });
      }

      const referencedNums = new Set<number>();
      const hasMarkers = segments.some((s) => s.imageNum !== undefined);
      let pdfImageCounter = 0;
      if (segments.length > 0) {
        for (const seg of segments) {
          if (seg.imageNum !== undefined) {
            const src = imageByContextIndex.get(seg.imageNum) || imageSources[seg.imageNum - 1];
            if (src) {
              referencedNums.add(seg.imageNum);
              pdfImageCounter += 1;
              await drawInlineImage(src, pdfImageCounter);
            }
            continue;
          }
          if (seg.text && seg.text.trim()) {
            writeAnswerText(seg.text);
          }
        }
      } else {
        writeAnswerText(normalizedAnswer);
      }

      if (!hasMarkers) {
        for (const src of imageSources) {
          const idx = src.context_image_index;
          if (typeof idx === 'number' && referencedNums.has(idx)) {
            continue;
          }
          try {
            pdfImageCounter += 1;
            await drawInlineImage(src, pdfImageCounter);
          } catch {
            // Ignore individual image failures to keep export working.
          }
        }
      }

      const slug = (turn.question || 'answer')
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, '')
        .trim()
        .replace(/\s+/g, '-')
        .slice(0, 48) || `answer-${index + 1}`;

      const fileName = `${slug}.pdf`;
      try {
        doc.save(fileName);
      } catch {
        const blob = doc.output('blob');
        const blobUrl = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = blobUrl;
        anchor.download = fileName;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(blobUrl);
      }
      notifySuccess('Answer downloaded as PDF');
    } catch (error: any) {
      const msg = error?.message ? `Failed to download PDF: ${error.message}` : 'Failed to download PDF';
      notifyError(msg);
      console.error('PDF download error (SearchPage):', error);
    }
  };

  const activeTurns = activeConversation?.turns ?? [];

  return (
    <>
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
                  <div className="chunk-text">{chunk.text}</div>
                </div>
              ))}
            </div>
          </div>
        ) : activeConversation ? (
          activeTurns.length > 0 ? (
            <div className="search-chat">
              {activeTurns.map((turn, turnIndex) => (
                <div key={turn.id} className="search-turn" ref={turnIndex === 0 ? chatTopRef : undefined}>
                  <div className="search-question-card">
                    <h3>You asked</h3>
                    <div className="answer-text">{turn.question}</div>
                  </div>

                  <div className="search-answer">
                    <div className="search-answer-header">
                      <h2>Answer</h2>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleDownloadAnswerPdf(turn, turnIndex)}
                        aria-label="Download answer as PDF"
                      >
                        <FiDownload /> Download PDF
                      </button>
                    </div>
                    <div className="answer-text">
                      {(() => {
                        const normalizedAnswer = normalizeAnswerText(turn.answer);
                        const interleavedImages = getInterleavedImageSources(turn.sources);
                        const imageByContextIndex = new Map<number, InterleavedImageSource>();
                        for (const entry of interleavedImages) {
                          const idx = entry.source.context_image_index;
                          if (typeof idx === 'number') {
                            imageByContextIndex.set(idx, entry);
                          }
                        }

                        const IMAGE_MARKER = /\[Image\s+(\d+)(?:\s*[—–\-][^\]]*)?\]/gi;
                        const segments: Array<{ text: string; imageNum?: number }> = [];
                        let lastIndex = 0;
                        let m: RegExpExecArray | null;
                        IMAGE_MARKER.lastIndex = 0;
                        while ((m = IMAGE_MARKER.exec(normalizedAnswer)) !== null) {
                          if (m.index > lastIndex) {
                            segments.push({ text: normalizedAnswer.slice(lastIndex, m.index) });
                          }
                          segments.push({ text: '', imageNum: parseInt(m[1], 10) });
                          lastIndex = m.index + m[0].length;
                        }
                        if (lastIndex < normalizedAnswer.length) {
                          segments.push({ text: normalizedAnswer.slice(lastIndex) });
                        }

                        let inlineImageCounter = 0;

                        return (
                          <>
                            {segments.length > 1 || (segments.length === 1 && segments[0].imageNum !== undefined) ? (
                              segments.map((seg, si) => {
                                if (seg.imageNum !== undefined) {
                                  const entry = imageByContextIndex.get(seg.imageNum);
                                  if (entry) {
                                    inlineImageCounter += 1;
                                    return (
                                      <div key={`img-block-${turn.id}-${entry.key}`} className="chat-interleaved-image-block">
                                        <div className="chat-interleaved-image-head">Image {inlineImageCounter}</div>
                                        <SourceImagePreview
                                          source={entry.source}
                                          blogId={entry.blogId}
                                          imageId={entry.imageId}
                                          onOpen={handleOpenSourceImage}
                                        />
                                      </div>
                                    );
                                  }
                                  return null;
                                }
                                return seg.text
                                  ? <p key={`${turn.id}-seg-${si}`}>{seg.text}</p>
                                  : null;
                              })
                            ) : (
                              normalizedAnswer.split(/\n\s*\n/).filter(Boolean).map((p, pi) => (
                                <p key={`${turn.id}-p-${pi}`}>{p.trim()}</p>
                              ))
                            )}
                            {/* Images are ONLY shown when the LLM explicitly references them with [Image N] markers. */}
                            {searching && activeTurnId === turn.id && <span className="cursor-blink">|</span>}
                          </>
                        );
                      })()}
                    </div>

                    {turn.sources.length > 0 && (
                      <div className="sources-toggle-block">
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => toggleSources(turn.id)}>
                          <FiDatabase /> {expandedSources[turn.id] ? 'Hide Sources' : `Show Sources (${turn.sources.length})`}
                        </button>

                        {expandedSources[turn.id] && (
                          <div className="sources-section">
                            <h3>Sources ({turn.sources.length})</h3>
                            {turn.sources.map((src, i) => {
                              const { blogId, imageId } = resolveSourceImageRef(src);
                              return (
                                <div key={i} className="source-card">
                                  <div className="source-title">{src.title}</div>
                                  <div className="source-meta">
                                    By {src.author} &middot; {src.organization}
                                    {src.created_at && <> &middot; {new Date(src.created_at).toLocaleDateString()}</>}
                                  </div>
                                  <SourceImagePreview
                                    source={src}
                                    blogId={blogId}
                                    imageId={imageId}
                                    onOpen={handleOpenSourceImage}
                                  />
                                  <div className="source-chunk">{src.chunk_text}</div>
                                </div>
                              );
                            })}
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
    {imagePreview && (
      <div className="image-modal-backdrop" onClick={() => setImagePreview(null)}>
        <div className="image-modal-content" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="image-modal-close"
            onClick={() => setImagePreview(null)}
            aria-label="Close image preview"
          >
            ×
          </button>
          <div className="image-modal-label">{imagePreview.name}</div>
          <img src={imagePreview.url} alt={imagePreview.name} className="image-modal-img" />
        </div>
      </div>
    )}
    </>
  );
}
