import axios from 'axios';

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

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
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
  list: () => api.get('/blogs/'),
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
  delete: (blogId: string, imageId: string) =>
    api.delete(`/images/blogs/${blogId}/images/${imageId}`),
};

// ─── Search ───
export const searchApi = {
  index: () => api.post('/search/index'),
  query: (question: string, detail_level: string = 'normal') =>
    api.post('/search/query', { question, detail_level }),
  chunks: () => api.get('/search/chunks'),
};

export default api;
