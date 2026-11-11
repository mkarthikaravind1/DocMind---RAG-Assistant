// config.js
// Single source of truth for the backend URL.
// Override at build/start time with REACT_APP_API_URL (e.g. in Frontend/.env).
export const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// FastAPI returns `detail` as a string for HTTPException and as a list for
// validation errors (422). This turns either into a readable message.
export function errorMessage(data, fallback) {
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map(d => String(d.msg || '').replace(/^Value error, /, ''))
      .filter(Boolean)
      .join('. ') || fallback;
  }
  return fallback;
}
