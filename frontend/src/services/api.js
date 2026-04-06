import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

const api = axios.create({
  baseURL: API_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

// Auth
export const authAPI = {
  register: (data) => api.post('/api/auth/register', data),
  login: (data) => api.post('/api/auth/login', data),
  logout: () => api.post('/api/auth/logout'),
  me: () => api.get('/api/auth/me'),
  refresh: () => api.post('/api/auth/refresh'),
};

// Items
export const itemsAPI = {
  save: (url) => api.post('/api/save', { url }),
  list: (params) => api.get('/api/items', { params }),
  get: (id) => api.get(`/api/items/${id}`),
  update: (id, data) => api.put(`/api/items/${id}`, data),
  delete: (id) => api.delete(`/api/items/${id}`),
  retry: (id) => api.post(`/api/items/${id}/retry`),
};

// Collections
export const collectionsAPI = {
  list: () => api.get('/api/collections'),
  create: (data) => api.post('/api/collections', data),
  get: (id) => api.get(`/api/collections/${id}`),
  update: (id, data) => api.put(`/api/collections/${id}`, data),
  delete: (id) => api.delete(`/api/collections/${id}`),
  addItem: (collectionId, itemId) => api.post(`/api/collections/${collectionId}/items`, { item_id: itemId }),
  removeItem: (collectionId, itemId) => api.delete(`/api/collections/${collectionId}/items/${itemId}`),
  getAvailableItems: (collectionId) => api.get(`/api/collections/${collectionId}/available-items`),
};

// Search
export const searchAPI = {
  search: (params) => api.get('/api/search', { params }),
};

// Map
export const mapAPI = {
  getItems: (params) => api.get('/api/map', { params }),
};

// Categories
export const categoriesAPI = {
  list: () => api.get('/api/categories'),
};

// Health
export const healthAPI = {
  check: () => api.get('/api/health'),
};

export function formatApiErrorDetail(detail) {
  if (detail == null) return 'Something went wrong. Please try again.';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e.msg === 'string' ? e.msg : JSON.stringify(e))).filter(Boolean).join(' ');
  if (detail && typeof detail.msg === 'string') return detail.msg;
  return String(detail);
}

export default api;
