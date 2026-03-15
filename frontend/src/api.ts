import axios from 'axios';
import { notifyError } from './utils/toast';

const isAuthPagePath = () => {
  const path = window.location.pathname.toLowerCase();
  return path === '/login' || path === '/signup';
};

export function handleSessionExpired() {
  localStorage.removeItem('token');
  localStorage.removeItem('refresh_token');
  if (!isAuthPagePath()) {
    notifyError('Your session has expired. Please log in again.');
  }
  if (window.location.pathname !== '/login') {
    window.location.replace('/login');
  }
}

// In dev: '/api' proxied by Vite to localhost:8000
// In prod: '' (same origin, served by FastAPI)
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Track if we're already refreshing to avoid infinite loops
let isRefreshing = false;
let refreshQueue: Array<(token: string) => void> = [];

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config || {};
    const requestUrl = String(originalRequest.url || '');
    const hadAuthHeader = Boolean(originalRequest.headers?.Authorization);
    const isAuthRequest =
      requestUrl.includes('/auth/login') ||
      requestUrl.includes('/auth/signup') ||
      requestUrl.includes('/auth/refresh');

    // If 401 and we haven't already tried to refresh for this request
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isAuthRequest || !hadAuthHeader) {
        return Promise.reject(error);
      }

      const refreshToken = localStorage.getItem('refresh_token');

      // No refresh token → session expired prompt
      if (!refreshToken) {
        handleSessionExpired();
        return Promise.reject(error);
      }

      // If already refreshing, queue this request
      if (isRefreshing) {
        return new Promise((resolve) => {
          refreshQueue.push((newToken: string) => {
            originalRequest.headers.Authorization = `Bearer ${newToken}`;
            resolve(api(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const res = await axios.post(
          `${import.meta.env.VITE_API_BASE_URL ?? '/api'}/auth/refresh`,
          { refresh_token: refreshToken }
        );
        const newAccess = res.data.access_token;
        const newRefresh = res.data.refresh_token;

        localStorage.setItem('token', newAccess);
        localStorage.setItem('refresh_token', newRefresh);

        // Retry all queued requests
        refreshQueue.forEach((cb) => cb(newAccess));
        refreshQueue = [];

        // Retry the original request
        originalRequest.headers.Authorization = `Bearer ${newAccess}`;
        return api(originalRequest);
      } catch {
        // Refresh failed → session truly expired
        handleSessionExpired();
        return Promise.reject(error);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

// ─── Auth ───
export const authApi = {
  signup: (data: { email: string; password: string; organization: string }) =>
    api.post('/auth/signup', data),
  login: (data: { email: string; password: string; organization: string }) =>
    api.post('/auth/login', data),
  me: () => api.get('/auth/me'),
};

// ─── Blogs ───
export const blogsApi = {
  list: () => api.get('/blogs/', { params: { _ts: Date.now() } }),
  changes: () => api.get('/blogs/changes', { params: { _ts: Date.now() } }),
  get: (id: string) => api.get(`/blogs/${id}`),
  create: (data: { title: string; content?: string }) =>
    api.post('/blogs/', data),
  update: (id: string, data: { title?: string; content?: string; status?: string }) =>
    api.put(`/blogs/${id}`, data),
  delete: (id: string) => api.delete(`/blogs/${id}`),
};

// ─── PDFs ───
export const pdfsApi = {
  list: (blogId: string) => api.get(`/pdfs/blogs/${blogId}`),
  upload: (blogId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post(`/pdfs/blogs/${blogId}/upload`, form);
  },
  view: (blogId: string, pdfId: string) =>
    api.get(`/pdfs/blogs/${blogId}/pdfs/${pdfId}/view`, { responseType: 'blob' }),
  delete: (blogId: string, pdfId: string) =>
    api.delete(`/pdfs/blogs/${blogId}/pdfs/${pdfId}`),
};

// ─── Images ───
export const imagesApi = {
  list: (blogId: string) => api.get(`/images/blogs/${blogId}`),
  upload: (blogId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post(`/images/blogs/${blogId}/upload`, form);
  },
  view: (blogId: string, imageId: string) =>
    api.get(`/images/blogs/${blogId}/images/${imageId}/view`, { responseType: 'blob' }),
  delete: (blogId: string, imageId: string) =>
    api.delete(`/images/blogs/${blogId}/images/${imageId}`),
};

// ─── Search ───
export const searchApi = {
  index: () => api.post('/search/index'),
  query: (question: string, detail_level: string = 'normal') =>
    api.post('/search/query', { question, detail_level }),
  chunks: () => api.get('/search/chunks'),
  listConversations: () => api.get('/search/conversations'),
  createConversation: (data?: { title?: string }) => api.post('/search/conversations', data ?? {}),
  updateConversation: (conversationId: string, data: { title: string; turns: Array<{ id: string; question: string; answer: string; sources: any[] }> }) =>
    api.put(`/search/conversations/${conversationId}`, data),
  deleteConversation: (conversationId: string) => api.delete(`/search/conversations/${conversationId}`),
};

export default api;
