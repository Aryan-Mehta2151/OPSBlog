import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { blogsApi, pdfsApi, imagesApi } from '../api';
import { useAuth } from '../context/AuthContext';
import { FiEdit, FiTrash2, FiUpload, FiFile, FiImage, FiSave, FiX, FiEye, FiExternalLink } from 'react-icons/fi';
import { getApiErrorMessage, notifyError, notifySuccess } from '../utils/toast';
import './BlogDetail.css';

interface Blog {
  id: string;
  title: string;
  content: string;
  status: string;
  author_id: string;
  org_id: string;
  created_at: string;
  updated_at: string;
}

interface PdfDoc {
  id: string;
  filename: string;
  file_path: string;
  uploaded_at: string;
}

interface ImageDoc {
  id: string;
  filename: string;
  file_path: string;
  uploaded_at: string;
}

export default function BlogDetailPage() {
  const { blogId } = useParams<{ blogId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [blog, setBlog] = useState<Blog | null>(null);
  const [pdfs, setPdfs] = useState<PdfDoc[]>([]);
  const [images, setImages] = useState<ImageDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Edit mode
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editStatus, setEditStatus] = useState('');
  const [saving, setSaving] = useState(false);

  // Upload state
  const [uploading, setUploading] = useState('');
  const [viewingPdfId, setViewingPdfId] = useState<string | null>(null);
  const [viewingImageId, setViewingImageId] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<{ name: string; url: string } | null>(null);
  const pdfInputRef = useRef<HTMLInputElement>(null);
  const imgInputRef = useRef<HTMLInputElement>(null);

  const isAuthor = blog?.author_id === user?.id;

  const fetchBlog = async () => {
    try {
      const [blogRes, pdfRes, imgRes] = await Promise.all([
        blogsApi.get(blogId!),
        pdfsApi.list(blogId!),
        imagesApi.list(blogId!),
      ]);
      setBlog(blogRes.data);
      setPdfs(pdfRes.data);
      setImages(imgRes.data);
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to load blog');
      setError(msg);
      notifyError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBlog();
  }, [blogId]);

  useEffect(() => {
    return () => {
      if (imagePreview?.url) {
        URL.revokeObjectURL(imagePreview.url);
      }
    };
  }, [imagePreview]);

  const startEdit = () => {
    if (!blog) return;
    setEditTitle(blog.title);
    setEditContent(blog.content);
    setEditStatus(blog.status);
    setEditing(true);
  };

  const cancelEdit = () => setEditing(false);

  const saveEdit = async () => {
    setSaving(true);
    try {
      const res = await blogsApi.update(blogId!, {
        title: editTitle,
        content: editContent,
        status: editStatus,
      });
      setBlog(res.data);
      setEditing(false);
      notifySuccess('Blog updated');
      navigate('/');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to update blog');
      setError(msg);
      notifyError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Delete this blog and all its attachments?')) return;
    try {
      await blogsApi.delete(blogId!);
      notifySuccess('Blog deleted');
      navigate('/');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to delete blog');
      setError(msg);
      notifyError(msg);
    }
  };

  const handlePdfUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading('pdf');
    try {
      await pdfsApi.upload(blogId!, file);
      const res = await pdfsApi.list(blogId!);
      setPdfs(res.data);
      notifySuccess('PDF uploaded');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'PDF upload failed');
      setError(msg);
      notifyError(msg);
    } finally {
      setUploading('');
      if (pdfInputRef.current) pdfInputRef.current.value = '';
    }
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading('image');
    try {
      await imagesApi.upload(blogId!, file);
      const res = await imagesApi.list(blogId!);
      setImages(res.data);
      notifySuccess('Image uploaded');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Image upload failed');
      setError(msg);
      notifyError(msg);
    } finally {
      setUploading('');
      if (imgInputRef.current) imgInputRef.current.value = '';
    }
  };

  const handleDeletePdf = async (pdfId: string) => {
    if (!window.confirm('Delete this PDF?')) return;
    try {
      await pdfsApi.delete(blogId!, pdfId);
      setPdfs((prev) => prev.filter((p) => p.id !== pdfId));
      notifySuccess('PDF deleted');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to delete PDF');
      setError(msg);
      notifyError(msg);
    }
  };

  const handleDeleteImage = async (imageId: string) => {
    if (!window.confirm('Delete this image?')) return;
    try {
      await imagesApi.delete(blogId!, imageId);
      setImages((prev) => prev.filter((i) => i.id !== imageId));
      notifySuccess('Image deleted');
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to delete image');
      setError(msg);
      notifyError(msg);
    }
  };

  const handleViewPdf = async (pdf: PdfDoc) => {
    const previewWindow = window.open('', '_blank');
    if (previewWindow) {
      previewWindow.document.title = pdf.filename;
      previewWindow.document.body.innerHTML = '<div style="font-family: sans-serif; padding: 24px; color: #0f172a;">Loading PDF...</div>';
    }

    try {
      setViewingPdfId(pdf.id);
      setError('');
      const res = await pdfsApi.view(blogId!, pdf.id);
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }));
      if (previewWindow) {
        previewWindow.location.href = url;
      } else {
        window.location.href = url;
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err: any) {
      if (previewWindow) {
        previewWindow.close();
      }
      const msg = getApiErrorMessage(err, 'Failed to open PDF');
      setError(msg);
      notifyError(msg);
    } finally {
      setViewingPdfId(null);
    }
  };

  const handleViewImage = async (image: ImageDoc) => {
    try {
      setViewingImageId(image.id);
      setError('');
      const res = await imagesApi.view(blogId!, image.id);
      const nextUrl = URL.createObjectURL(res.data);
      setImagePreview((prev) => {
        if (prev?.url) {
          URL.revokeObjectURL(prev.url);
        }
        return { name: image.filename, url: nextUrl };
      });
    } catch (err: any) {
      const msg = getApiErrorMessage(err, 'Failed to open image');
      setError(msg);
      notifyError(msg);
    } finally {
      setViewingImageId(null);
    }
  };

  const closeImagePreview = () => {
    setImagePreview((prev) => {
      if (prev?.url) {
        URL.revokeObjectURL(prev.url);
      }
      return null;
    });
  };

  if (loading) return <div className="loading">Loading...</div>;
  if (!blog) return <div className="loading">Blog not found.</div>;

  return (
    <div className="blog-detail">
      {/* Header */}
      <div className="detail-header">
        {editing ? (
          <input
            className="edit-title-input"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
          />
        ) : (
          <h1>{blog.title}</h1>
        )}
        <span className={`status-badge ${blog.status}`}>{blog.status}</span>
      </div>

      <div className="detail-meta">
        Created: {new Date(blog.created_at).toLocaleString()}
        {blog.updated_at && <> &middot; Updated: {new Date(blog.updated_at).toLocaleString()}</>}
      </div>

      {/* Actions */}
      {isAuthor && (
        <div className="detail-actions">
          {editing ? (
            <>
              <select value={editStatus} onChange={(e) => setEditStatus(e.target.value)}>
                <option value="draft">Draft</option>
                <option value="published">Published</option>
              </select>
              <button className="btn btn-primary btn-sm" onClick={saveEdit} disabled={saving}>
                <FiSave /> {saving ? 'Saving...' : 'Save'}
              </button>
              <button className="btn btn-secondary btn-sm" onClick={cancelEdit}>
                <FiX /> Cancel
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-secondary btn-sm" onClick={startEdit}>
                <FiEdit /> Edit
              </button>
              <button className="btn btn-danger btn-sm" onClick={handleDelete}>
                <FiTrash2 /> Delete
              </button>
            </>
          )}
        </div>
      )}

      {/* Content */}
      <div className="detail-content">
        {editing ? (
          <textarea
            className="edit-content-textarea"
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            rows={15}
          />
        ) : (
          <div className="blog-body">{blog.content || <em>No content yet.</em>}</div>
        )}
      </div>

      {/* Attachments - only show for published blogs */}
      {blog.status === 'published' && (
        <div className="attachments-section">
          {/* PDFs */}
          <div className="attachment-group">
            <div className="attachment-header">
              <h3><FiFile /> PDFs ({pdfs.length})</h3>
              {isAuthor && (
                <>
                  <input
                    ref={pdfInputRef}
                    type="file"
                    accept=".pdf"
                    onChange={handlePdfUpload}
                    hidden
                  />
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => pdfInputRef.current?.click()}
                    disabled={uploading === 'pdf'}
                  >
                    <FiUpload /> {uploading === 'pdf' ? 'Uploading...' : 'Upload PDF'}
                  </button>
                </>
              )}
            </div>
            {pdfs.length === 0 ? (
              <p className="no-attachments">No PDFs attached.</p>
            ) : (
              <ul className="attachment-list">
                {pdfs.map((pdf) => (
                  <li key={pdf.id}>
                    <FiFile /> {pdf.filename}
                    <span className="attach-date">{new Date(pdf.uploaded_at).toLocaleDateString()}</span>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm attachment-view-btn"
                      onClick={() => handleViewPdf(pdf)}
                      disabled={viewingPdfId === pdf.id}
                    >
                      <FiExternalLink /> {viewingPdfId === pdf.id ? 'Opening...' : 'View'}
                    </button>
                    {isAuthor && (
                      <button type="button" className="btn-icon-danger" onClick={() => handleDeletePdf(pdf.id)}>
                        <FiTrash2 />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Images */}
          <div className="attachment-group">
            <div className="attachment-header">
              <h3><FiImage /> Images ({images.length})</h3>
              {isAuthor && (
                <>
                  <input
                    ref={imgInputRef}
                    type="file"
                    accept="image/*"
                    onChange={handleImageUpload}
                    hidden
                  />
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => imgInputRef.current?.click()}
                    disabled={uploading === 'image'}
                  >
                    <FiUpload /> {uploading === 'image' ? 'Uploading...' : 'Upload Image'}
                  </button>
                </>
              )}
            </div>
            {images.length === 0 ? (
              <p className="no-attachments">No images attached.</p>
            ) : (
              <ul className="attachment-list">
                {images.map((img) => (
                  <li key={img.id}>
                    <FiImage /> {img.filename}
                    <span className="attach-date">{new Date(img.uploaded_at).toLocaleDateString()}</span>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm attachment-view-btn"
                      onClick={() => handleViewImage(img)}
                      disabled={viewingImageId === img.id}
                    >
                      <FiEye /> {viewingImageId === img.id ? 'Opening...' : 'View'}
                    </button>
                    {isAuthor && (
                      <button type="button" className="btn-icon-danger" onClick={() => handleDeleteImage(img.id)}>
                        <FiTrash2 />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {imagePreview && (
        <div className="image-preview-overlay" onClick={closeImagePreview} role="presentation">
          <div className="image-preview-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={imagePreview.name}>
            <div className="image-preview-header">
              <h3>{imagePreview.name}</h3>
              <button type="button" className="btn btn-secondary btn-sm" onClick={closeImagePreview}>
                <FiX /> Close
              </button>
            </div>
            <div className="image-preview-body">
              <img src={imagePreview.url} alt={imagePreview.name} className="image-preview-content" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
