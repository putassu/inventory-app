export const API_BASE = 'http://localhost:9005';

export const getAuthHeaders = () => {
  const token = localStorage.getItem('token');
  return token ? { 'Authorization': `Bearer ${token}` } : {};
};

export const apiCall = async (endpoint, options = {}) => {
  const headers = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
    ...options.headers,
  };

  if (options.body instanceof FormData) {
    delete headers['Content-Type']; // Let browser set boundary
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  if (!response.ok) {
    const errData = await response.json().catch(() => null);
    throw new Error(errData?.detail || `Error ${response.status}`);
  }

  if (response.status !== 204) {
    return response.json();
  }
};
