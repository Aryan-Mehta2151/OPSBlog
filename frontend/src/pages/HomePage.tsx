import { useState, useRef, useEffect, useMemo } from 'react';
import { documentsApi, searchApi, handleSessionExpired } from '../api';
import { useAuth } from '../context/AuthContext';
import {
  FiFileText, FiFile, FiImage, FiPlus, FiSearch,
  FiRefreshCw, FiDatabase, FiTrash2, FiX, FiEye,
  FiChevronDown, FiChevronUp, FiUpload, FiCopy, FiCheck, FiDownload,
} from 'react-icons/fi';
import { jsPDF } from 'jspdf';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import './Search.css';
import './HomePage.css';

// â”€â”€ shared types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface DocItem {
  type: 'text' | 'pdf' | 'image';
  id: string;
  blog_id: string;
  title: string;
  content?: string;
  filename?: string;
  created_at: string;
}

interface Source {
  title: string;
  author: string;
  organization: string;
  created_at: string;
  chunk_text: string;
  type?: string;
  blog_id?: string;
  image_id?: string;
  pdf_id?: string;
  filename?: string;
  source_pdf_id?: string;
  source_pdf_filename?: string;
  context_image_index?: number;
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
  blogId: string;
  imageId: string;
  narrative: string;
  key: string;
}

const extractImageNarrative = (chunkText: string, fallbackTitle: string) => {
  const text = (chunkText || '').trim();
  if (!text) return `Relevant visual match for ${fallbackTitle}.`;

  const imageDescriptionMatch = text.match(/Image Description:\s*([\s\S]*?)(?:\n\s*Extracted Text:|$)/i);
  if (imageDescriptionMatch?.[1]?.trim()) {
    return imageDescriptionMatch[1].trim();
  }

  const cleaned = text
    .replace(/\bImage:\s*/gi, '')
    .replace(/\bExtracted Text:\s*/gi, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!cleaned) return `Relevant visual match for ${fallbackTitle}.`;
  return cleaned.length > 320 ? `${cleaned.slice(0, 317).trim()}...` : cleaned;
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
  const [loading, setLoading] = useState(false);
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
      {loading && <div className="source-image-loading">Loading image...</div>}
      {error && <div className="source-image-error">{error}</div>}
      {!loading && !error && imageUrl && (
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

const buildConversationTitle = (query: string) => {
  const normalized = query.trim().replace(/\s+/g, ' ');
  if (normalized.length <= 40) return normalized;
  return `${normalized.slice(0, 40).trim()}...`;
};

// â”€â”€ component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export default function HomePage() {
  const { isAdmin, user, loading } = useAuth();

  // â”€â”€ knowledge base â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const [kbOpen, setKbOpen] = useState(true);
  const [documents, setDocuments] = useState<DocItem[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // text modal
  const [textModalOpen, setTextModalOpen] = useState(false);
  const [textTitle, setTextTitle] = useState('');
  const [textContent, setTextContent] = useState('');
  const [savingText, setSavingText] = useState(false);

  // expand / preview
  const [expandedTextId, setExpandedTextId] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<{ url: string; name: string } | null>(null);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const pdfInputRef = useRef<HTMLInputElement>(null);
  const imgInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = async () => {
    setLoadingDocs(true);
    try {
      const res = await documentsApi.list();
      setDocuments(Array.isArray(res.data) ? res.data : []);
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to load documents'));
    } finally {
      setLoadingDocs(false);
    }
  };

  useEffect(() => {
    loadDocuments();
  }, []);

  // cleanup image preview blob on unmount
  useEffect(() => {
    return () => {
      if (imagePreview?.url) URL.revokeObjectURL(imagePreview.url);
    };
  }, [imagePreview]);

  const handleAddPdf = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setUploadingPdf(true);
    try {
      await documentsApi.addPdf(file);
      notifySuccess(`"${file.name}" uploaded and indexed`);
      await loadDocuments();
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'PDF upload failed'));
    } finally {
      setUploadingPdf(false);
    }
  };

  const handleAddImage = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setUploadingImage(true);
    try {
      await documentsApi.addImage(file);
      notifySuccess(`"${file.name}" uploaded and indexed`);
      await loadDocuments();
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Image upload failed'));
    } finally {
      setUploadingImage(false);
    }
  };

  const handleSaveText = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!textTitle.trim()) return;
    setSavingText(true);
    try {
      await documentsApi.addText({ title: textTitle.trim(), content: textContent });
      notifySuccess('Text entry saved and indexed');
      setTextModalOpen(false);
      setTextTitle('');
      setTextContent('');
      await loadDocuments();
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to save text entry'));
    } finally {
      setSavingText(false);
    }
  };

  const handleDelete = async (doc: DocItem) => {
    if (!window.confirm(`Delete "${doc.title || doc.filename}"?`)) return;
    setDeletingId(doc.id);
    try {
      if (doc.type === 'text') await documentsApi.deleteText(doc.id);
      else if (doc.type === 'pdf') await documentsApi.deletePdf(doc.id);
      else await documentsApi.deleteImage(doc.id);
      notifySuccess('Deleted');
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
      if (expandedTextId === doc.id) setExpandedTextId(null);
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Delete failed'));
    } finally {
      setDeletingId(null);
    }
  };

  const handleViewPdf = async (doc: DocItem) => {
    const win = window.open('', '_blank');
    if (win) win.document.body.innerHTML = '<div style="font-family:sans-serif;padding:24px">Loading PDF...</div>';
    setViewingId(doc.id);
    try {
      const res = await documentsApi.viewPdf(doc.blog_id, doc.id);
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      if (win) win.location.href = url;
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err: any) {
      if (win) win.close();
      notifyError(getApiErrorMessage(err, 'Failed to open PDF'));
    } finally {
      setViewingId(null);
    }
  };

  const handleViewImage = async (doc: DocItem) => {
    setViewingId(doc.id);
    try {
      const res = await documentsApi.viewImage(doc.blog_id, doc.id);
      const url = URL.createObjectURL(res.data);
      setImagePreview((prev) => {
        if (prev?.url) URL.revokeObjectURL(prev.url);
        return { url, name: doc.filename || doc.title };
      });
    } catch (err: any) {
      notifyError(getApiErrorMessage(err, 'Failed to open image'));
    } finally {
      setViewingId(null);
    }
  };

  const resolveSourceImageRef = (source: Source): { blogId: string | null; imageId: string | null } => {
    if (source.blog_id && source.image_id) {
      return { blogId: source.blog_id, imageId: source.image_id };
    }

    if (!source.blog_id || !source.filename) {
      return { blogId: null, imageId: null };
    }

    const fallback = documents.find(
      (doc) => doc.type === 'image' && doc.blog_id === source.blog_id && doc.filename === source.filename,
    );

    return { blogId: source.blog_id, imageId: fallback?.id ?? null };
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
        narrative: extractImageNarrative(src.chunk_text, src.filename || src.title),
        key,
      });
    }

    return collected;
  };

  // â”€â”€ chat state (identical to SearchPage) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const [question, setQuestion] = useState('');
  const [detailLevel, setDetailLevel] = useState('normal');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [chatError, setChatError] = useState('');
  const [indexing, setIndexing] = useState(false);
  const [indexMsg, setIndexMsg] = useState('');
  const [chunks, setChunks] = useState<any[]>([]);
  const [showChunks, setShowChunks] = useState(false);
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const copyResetRef = useRef<number | null>(null);
  const conversationsRef = useRef<Conversation[]>([]);

  useEffect(() => { conversationsRef.current = conversations; }, [conversations]);

  useEffect(() => {
    if (!indexMsg) return;
    const timeoutId = window.setTimeout(() => setIndexMsg(''), 4000);
    return () => window.clearTimeout(timeoutId);
  }, [indexMsg]);

  useEffect(() => {
    return () => {
      if (copyResetRef.current) {
        window.clearTimeout(copyResetRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      setConversations([]);
      setActiveConversationId(null);
      return;
    }
    const loadConversations = async () => {
      setLoadingConversations(true);
      try {
        const res = await searchApi.listConversations();
        const loaded = (res.data ?? []).map((c: any) => ({
          id: c.id, title: c.title, createdAt: c.created_at, updatedAt: c.updated_at, turns: c.turns ?? [],
        }));
        setConversations(loaded);
        setActiveConversationId((prev) => {
          if (prev && loaded.some((c: Conversation) => c.id === prev)) return prev;
          return loaded[0]?.id ?? null;
        });
      } catch (err: any) {
        setChatError(getApiErrorMessage(err, 'Failed to load saved chats'));
      } finally {
        setLoadingConversations(false);
      }
    };
    loadConversations();
  }, [loading, user]);

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeConversationId) ?? null,
    [activeConversationId, conversations],
  );

  const upsertConversationLocally = (next: Conversation, moveToTop = true) => {
    setConversations((prev) => {
      const remaining = prev.filter((c) => c.id !== next.id);
      return moveToTop ? [next, ...remaining] : [...remaining, next];
    });
  };

  const updateTurn = (convId: string, turnId: string, updater: (t: ChatTurn) => ChatTurn) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId
          ? { ...c, updatedAt: new Date().toISOString(), turns: c.turns.map((t) => (t.id === turnId ? updater(t) : t)) }
          : c,
      ),
    );
  };

  const persistConversation = async (conversation: Conversation) => {
    const res = await searchApi.updateConversation(conversation.id, {
      title: conversation.title,
      turns: conversation.turns.map((t) => ({ id: t.id, question: t.question, answer: t.answer, sources: t.sources })),
    });
    const saved: Conversation = {
      id: res.data.id, title: res.data.title,
      createdAt: res.data.created_at, updatedAt: res.data.updated_at, turns: res.data.turns ?? [],
    };
    upsertConversationLocally(saved, true);
    return saved;
  };

  const createConversation = async () => {
    const res = await searchApi.createConversation({ title: 'New chat' });
    const next: Conversation = {
      id: res.data.id, title: res.data.title,
      createdAt: res.data.created_at, updatedAt: res.data.updated_at, turns: res.data.turns ?? [],
    };
    upsertConversationLocally(next, true);
    setActiveConversationId(next.id);
    setShowChunks(false);
    setChatError('');
    return next;
  };

  const refreshAccessToken = async (base: string): Promise<string | null> => {
    const rt = localStorage.getItem('refresh_token');
    if (!rt) return null;
    try {
      const r = await fetch(`${base}/auth/refresh`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!r.ok) return null;
      const data = await r.json();
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      return data.access_token;
    } catch { return null; }
  };

  const streamSearch = async (
    query: string, conversationId: string, turnId: string,
    token: string | null, hasRetried = false,
  ): Promise<StreamResult> => {
    const base = (import.meta.env.VITE_API_BASE_URL || '/api').trim() || '/api';

    const res = await fetch(`${base}/search/query/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({
        question: query,
        detail_level: detailLevel,
      }),
    });

    if (!res.ok) {
      if (res.status === 401 && !hasRetried) {
        const newToken = await refreshAccessToken(base);
        if (newToken) return streamSearch(query, conversationId, turnId, newToken, true);
        handleSessionExpired();
        return { answer: '', sources: [] };
      }
      const errData = await res.json().catch(() => null);
      throw new Error(errData?.detail || `HTTP ${res.status}`);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error('No stream received from server');

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
            updateTurn(conversationId, turnId, (t) => ({ ...t, answer: t.answer + msg.content }));
          } else if (msg.type === 'sources') {
            finalSources = msg.sources || [];
            updateTurn(conversationId, turnId, (t) => ({ ...t, sources: msg.sources || [] }));
          }
        } catch { /* ignore non-JSON SSE */ }
      }
    }
    return { answer: fullAnswer, sources: finalSources };
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const query = question.trim();
    if (!query) return;

    let target = activeConversation;
    if (!target) {
      try { target = await createConversation(); }
      catch (err: any) { setChatError(err.response?.data?.detail || 'Failed to create chat'); return; }
    }

    const convId = target.id;
    const turnId = `${Date.now()}`;
    const turn: ChatTurn = { id: turnId, question: query, answer: '', sources: [] };
    const updated: Conversation = {
      ...target,
      title: target.turns.length === 0 ? buildConversationTitle(query) : target.title,
      updatedAt: new Date().toISOString(),
      turns: [turn, ...target.turns],
    };

    upsertConversationLocally(updated, true);
    setActiveConversationId(convId);
    setActiveTurnId(turnId);
    setSearching(true);
    setShowChunks(false);
    setIndexMsg('');
    setChatError('');
    setQuestion('');

    try {
      await persistConversation(updated);
      const token = localStorage.getItem('token');
      const result = await streamSearch(query, convId, turnId, token);
      const finalized: Conversation = {
        ...updated,
        updatedAt: new Date().toISOString(),
        turns: updated.turns.map((t) =>
          t.id === turnId ? { ...t, answer: result.answer, sources: result.sources } : t,
        ),
      };
      upsertConversationLocally(finalized, true);
      await persistConversation(finalized);
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Search failed');
      setChatError(msg);
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
    } finally { setIndexing(false); }
  };

  const handleViewChunks = async () => {
    if (showChunks) { setShowChunks(false); return; }
    try {
      const res = await searchApi.chunks();
      setChunks(res.data);
      setShowChunks(true);
    } catch (err: any) {
      setChatError(getApiErrorMessage(err, 'Failed to load chunks'));
    }
  };

  const handleNewChat = async () => {
    try { await createConversation(); setQuestion(''); }
    catch (err: any) { setChatError(getApiErrorMessage(err, 'Failed to create chat')); }
  };

  const handleCopy = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      if (copyResetRef.current) {
        window.clearTimeout(copyResetRef.current);
      }
      copyResetRef.current = window.setTimeout(() => setCopiedKey(null), 1800);
    } catch {
      notifyError('Failed to copy');
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

      const writeParagraph = (text: string, fontSize = 11, isBold = false) => {
        doc.setFont('helvetica', isBold ? 'bold' : 'normal');
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

      const normalizedAnswer = normalizeAnswerText(turn.answer || '');

      writeParagraph('Answer', 14, true);
      y += 8;

      const interleavedImages = getInterleavedImageSources(turn.sources);
      const imageByContextIndex = new Map<number, InterleavedImageSource>();
      for (const entry of interleavedImages) {
        const idx = entry.source.context_image_index;
        if (typeof idx === 'number') {
          imageByContextIndex.set(idx, entry);
        }
      }

      const drawInlineImage = async (entry: InterleavedImageSource, displayNum: number) => {
        const { blogId, imageId } = resolveSourceImageRef(entry.source);
        if (!blogId || !imageId) {
          return;
        }
        const res = await documentsApi.viewImage(blogId, imageId);
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
            const entry = imageByContextIndex.get(seg.imageNum);
            if (entry) {
              referencedNums.add(seg.imageNum);
              pdfImageCounter += 1;
              await drawInlineImage(entry, pdfImageCounter);
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

      // Match chat UI behavior exactly:
      // - when markers exist, show only referenced images
      // - when markers do not exist, append retrieved images
      if (!hasMarkers) {
        for (const entry of interleavedImages) {
          const idx = entry.source.context_image_index;
          if (typeof idx === 'number' && referencedNums.has(idx)) {
            continue;
          }
          try {
            pdfImageCounter += 1;
            await drawInlineImage(entry, pdfImageCounter);
          } catch {
            // Continue with remaining content even if one image fails.
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
        // Some browsers block direct save in async click handlers; fallback to blob URL.
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
      console.error('PDF download error (HomePage):', error);
    }
  };

  const handleDeleteConversation = async (convId: string) => {
    try {
      await searchApi.deleteConversation(convId);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      setExpandedSources((prev) => {
        const next = { ...prev };
        for (const t of conversationsRef.current.find((c) => c.id === convId)?.turns ?? []) delete next[t.id];
        return next;
      });
      setActiveConversationId((prev) => {
        if (prev !== convId) return prev;
        return conversationsRef.current.filter((c) => c.id !== convId)[0]?.id ?? null;
      });
      notifySuccess('Chat deleted');
    } catch (err: any) {
      setChatError(getApiErrorMessage(err, 'Failed to delete chat'));
    }
  };

  const activeTurns = activeConversation?.turns ?? [];

  // â”€â”€ render â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  return (
    <div className="home-page">

      {/* â”€â”€ Text modal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {textModalOpen && (
        <div className="modal-overlay" onClick={() => setTextModalOpen(false)} role="presentation">
          <div className="modal-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
            <div className="modal-header">
              <h2>Add Text Entry</h2>
              <button type="button" className="modal-close" onClick={() => setTextModalOpen(false)}>
                <FiX />
              </button>
            </div>
            <form onSubmit={handleSaveText}>
              <input
                className="entry-title"
                type="text"
                placeholder="Title"
                value={textTitle}
                onChange={(e) => setTextTitle(e.target.value)}
                required
                autoFocus
              />
              <textarea
                className="entry-content"
                placeholder="Write your content here..."
                rows={7}
                value={textContent}
                onChange={(e) => setTextContent(e.target.value)}
              />
              <div className="modal-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setTextModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={savingText || !textTitle.trim()}>
                  {savingText ? 'Saving...' : 'Save & Index'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* â”€â”€ Image preview modal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {imagePreview && (
        <div className="modal-overlay" onClick={() => setImagePreview(null)} role="presentation">
          <div className="modal-card modal-card--image" onClick={(e) => e.stopPropagation()} role="dialog">
            <div className="modal-header">
              <h2>{imagePreview.name}</h2>
              <button type="button" className="modal-close" onClick={() => setImagePreview(null)}><FiX /></button>
            </div>
            <img src={imagePreview.url} alt={imagePreview.name} className="image-preview-content" />
          </div>
        </div>
      )}

      {/* â”€â”€ Knowledge Base â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <section className="kb-section">
        <div className="kb-header">
          <h2 className="kb-title">Knowledge Base</h2>
          <div className="kb-actions">
            {/* hidden file inputs */}
            <input ref={pdfInputRef} type="file" accept=".pdf" onChange={handleAddPdf} hidden />
            <input ref={imgInputRef} type="file" accept="image/*" onChange={handleAddImage} hidden />

            <button
              type="button"
              className="btn btn-add-item"
              onClick={() => setTextModalOpen(true)}
            >
              <FiFileText /> Add Text
            </button>
            <button
              type="button"
              className="btn btn-add-item"
              onClick={() => pdfInputRef.current?.click()}
              disabled={uploadingPdf}
            >
              <FiUpload /> {uploadingPdf ? 'Uploading...' : 'Add PDF'}
            </button>
            <button
              type="button"
              className="btn btn-add-item"
              onClick={() => imgInputRef.current?.click()}
              disabled={uploadingImage}
            >
              <FiImage /> {uploadingImage ? 'Uploading...' : 'Add Image'}
            </button>

            <button
              type="button"
              className="kb-collapse-btn"
              onClick={() => setKbOpen((o) => !o)}
              aria-label={kbOpen ? 'Collapse' : 'Expand'}
            >
              {kbOpen ? <FiChevronUp /> : <FiChevronDown />}
            </button>
          </div>
        </div>

        {kbOpen && (
          <div className="kb-body">
            {loadingDocs ? (
              <p className="kb-empty">Loading files...</p>
            ) : documents.length === 0 ? (
              <p className="kb-empty">No files yet. Add a text entry, PDF, or image above.</p>
            ) : (
              <div className="doc-grid">
                {documents.map((doc) => (
                  <div key={doc.id} className={`doc-card doc-card--${doc.type}`}>
                    <div className="doc-card-icon">
                      {doc.type === 'text' && <FiFileText />}
                      {doc.type === 'pdf' && <FiFile />}
                      {doc.type === 'image' && <FiImage />}
                    </div>
                    <div className="doc-card-body">
                      <p className="doc-card-name">{doc.filename || doc.title}</p>
                      <p className="doc-card-date">
                        {new Date(doc.created_at).toLocaleDateString()}
                      </p>

                      {/* Expanded text preview */}
                      {doc.type === 'text' && expandedTextId === doc.id && (
                        <div className="doc-text-preview">{doc.content || <em>No content.</em>}</div>
                      )}
                    </div>
                    <div className="doc-card-actions">
                      {doc.type === 'text' && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => setExpandedTextId((id) => (id === doc.id ? null : doc.id))}
                        >
                          <FiEye /> {expandedTextId === doc.id ? 'Hide' : 'View'}
                        </button>
                      )}
                      {doc.type === 'pdf' && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleViewPdf(doc)}
                          disabled={viewingId === doc.id}
                        >
                          <FiEye /> {viewingId === doc.id ? 'Opening...' : 'View'}
                        </button>
                      )}
                      {doc.type === 'image' && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleViewImage(doc)}
                          disabled={viewingId === doc.id}
                        >
                          <FiEye /> {viewingId === doc.id ? 'Loading...' : 'View'}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn-icon-danger"
                        onClick={() => handleDelete(doc)}
                        disabled={deletingId === doc.id}
                        aria-label="Delete"
                      >
                        <FiTrash2 />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* â”€â”€ Chat â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="search-page home-chat">
        <aside className="search-sidebar">
          <button type="button" className="btn btn-primary search-new-chat" onClick={handleNewChat} disabled={searching}>
            <FiPlus /> New Chat
          </button>
          <div className="search-conversation-list">
            {loadingConversations ? (
              <div className="search-empty-state">Loading chats...</div>
            ) : conversations.length === 0 ? (
              <div className="search-empty-state">Your chats will appear here.</div>
            ) : (
              conversations.map((c) => (
                <div key={c.id} className={`search-conversation-item ${c.id === activeConversationId ? 'active' : ''}`}>
                  <button
                    type="button"
                    className="search-conversation-select"
                    onClick={() => { setActiveConversationId(c.id); setShowChunks(false); setChatError(''); }}
                  >
                    <span className="search-conversation-title">{c.title}</span>
                    <span className="search-conversation-meta">
                      {c.turns.length === 0 ? 'No messages yet' : `${c.turns.length} message${c.turns.length === 1 ? '' : 's'}`}
                    </span>
                  </button>
                  <button type="button" className="search-conversation-delete" onClick={() => handleDeleteConversation(c.id)} aria-label={`Delete ${c.title}`}>
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
              <h1>AI Knowledge Search</h1>
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
                  placeholder="Ask a question about your knowledge base..."
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
            {chatError && <div className="home-error-msg">{chatError}</div>}
          </div>

          {showChunks ? (
            <div className="chunks-section">
              <h2>Indexed Chunks ({chunks.length})</h2>
              <div className="chunks-list">
                {chunks.map((chunk, i) => (
                  <div key={i} className="chunk-card">
                    <div className="chunk-id">{chunk.id}</div>
                    <div className="chunk-meta">Type: {chunk.metadata?.type || 'text'} &middot; {chunk.metadata?.title || 'Unknown'}</div>
                    <div className="chunk-text">{chunk.text?.substring(0, 200)}...</div>
                  </div>
                ))}
              </div>
            </div>
          ) : activeConversation ? (
            activeTurns.length > 0 ? (
              <div className="search-chat">
                {activeTurns.map((turn, turnIndex) => (
                  <div key={turn.id} className="search-turn">
                    <div className="search-question-card">
                      <div className="chat-card-header">
                        <h3>You asked</h3>
                        <button
                          type="button"
                          className="chat-copy-btn"
                          onClick={() => handleCopy(turn.question, `question-${turn.id}`)}
                          aria-label="Copy question"
                        >
                          {copiedKey === `question-${turn.id}` ? <FiCheck /> : <FiCopy />}
                          {copiedKey === `question-${turn.id}` ? 'Copied' : 'Copy'}
                        </button>
                      </div>
                      <div className="answer-text">{turn.question}</div>
                    </div>
                    <div className="search-answer">
                      <div className="chat-card-header">
                        <h2>Answer</h2>
                        <div className="chat-card-actions">
                          <button
                            type="button"
                            className="chat-copy-btn"
                            onClick={() => handleCopy(normalizeAnswerText(turn.answer), `answer-${turn.id}`)}
                            aria-label="Copy answer"
                          >
                            {copiedKey === `answer-${turn.id}` ? <FiCheck /> : <FiCopy />}
                            {copiedKey === `answer-${turn.id}` ? 'Copied' : 'Copy'}
                          </button>
                          <button
                            type="button"
                            className="chat-copy-btn"
                            onClick={() => handleDownloadAnswerPdf(turn, turnIndex)}
                            aria-label="Download answer as PDF"
                          >
                            <FiDownload /> PDF
                          </button>
                        </div>
                      </div>
                      {(() => {
                        const normalizedAnswer = normalizeAnswerText(turn.answer || '');
                        const interleavedImages = getInterleavedImageSources(turn.sources);

                        // Build a lookup: context_image_index → image entry
                        const imageByContextIndex = new Map<number, InterleavedImageSource>();
                        for (const entry of interleavedImages) {
                          const idx = entry.source.context_image_index;
                          if (typeof idx === 'number') {
                            imageByContextIndex.set(idx, entry);
                          }
                        }

                        const renderVisualBlock = (entry: InterleavedImageSource, displayNum: number) => (
                          <div key={`img-block-${turn.id}-${entry.key}`} className="chat-interleaved-image-block">
                            <div className="chat-interleaved-image-head">Image {displayNum}</div>
                            <SourceImagePreview
                              source={entry.source}
                              blogId={entry.blogId}
                              imageId={entry.imageId}
                              onOpen={handleOpenSourceImage}
                            />
                          </div>
                        );

                        // Split answer text on [Image N] markers so each image is placed
                        // exactly where the AI referenced it, not positionally.
                        // Matches [Image 1], [Image 2], and also [Image 1 — Subject | file: ...] variants.
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

                        const referencedNums = new Set<number>();
                        const hasMarkers = segments.some((s) => s.imageNum !== undefined);
                        let inlineImageCounter = 0;

                        return (
                          <div className="answer-text">
                            {segments.length > 1 || (segments.length === 1 && segments[0].imageNum !== undefined) ? (
                              segments.map((seg, si) => {
                                if (seg.imageNum !== undefined) {
                                  const entry = imageByContextIndex.get(seg.imageNum);
                                  if (entry) {
                                    referencedNums.add(seg.imageNum);
                                    inlineImageCounter += 1;
                                    return renderVisualBlock(entry, inlineImageCounter);
                                  }
                                  return null;
                                }
                                return seg.text
                                  ? <p key={`${turn.id}-seg-${si}`}>{seg.text}</p>
                                  : null;
                              })
                            ) : (
                              // No [Image N] markers — render plain text
                              normalizedAnswer.split(/\n\s*\n/).filter(Boolean).map((p, pi) => (
                                <p key={`${turn.id}-p-${pi}`}>{p.trim()}</p>
                              ))
                            )}
                            {/* If no markers exist, fallback to showing retrieved images; otherwise keep strict marker alignment. */}
                            {!hasMarkers && interleavedImages
                              .filter(e => typeof e.source.context_image_index !== 'number' || !referencedNums.has(e.source.context_image_index))
                              .map((entry) => {
                                inlineImageCounter += 1;
                                return renderVisualBlock(entry, inlineImageCounter);
                              })}
                            {searching && activeTurnId === turn.id && <span className="cursor-blink">|</span>}
                          </div>
                        );
                      })()}
                      {turn.sources.length > 0 && (
                        <div className="sources-toggle-block">
                          <button type="button" className="btn btn-secondary btn-sm"
                            onClick={() => setExpandedSources((prev) => ({ ...prev, [turn.id]: !prev[turn.id] }))}>
                            <FiDatabase /> {expandedSources[turn.id] ? 'Hide Sources' : `Show Sources (${turn.sources.length})`}
                          </button>
                          {expandedSources[turn.id] && (
                            <div className="sources-section">
                              <h3>Sources ({turn.sources.length})</h3>
                              {turn.sources.map((src, i) => (
                                (() => {
                                  const { blogId, imageId } = resolveSourceImageRef(src);
                                  return (
                                    <div key={i} className="source-card">
                                      <div className="source-title">{src.title}</div>
                                      <div className="source-meta">By {src.author} &middot; {src.organization}{src.created_at && <> &middot; {new Date(src.created_at).toLocaleDateString()}</>}</div>
                                      <SourceImagePreview
                                        source={src}
                                        blogId={blogId}
                                        imageId={imageId}
                                        onOpen={handleOpenSourceImage}
                                      />
                                      <div className="source-chunk">{src.chunk_text}</div>
                                    </div>
                                  );
                                })()
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
                <p>Ask a question to get started.</p>
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
    </div>
  );
}
