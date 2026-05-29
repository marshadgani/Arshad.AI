// Base URL for all backend API calls.
// In dev (VITE_API_BASE_URL unset): empty string — Vite proxy forwards /api/* to localhost:8000.
// In production: set VITE_API_BASE_URL=https://<backend>.onrender.com in the Render frontend service.
// Trailing slash stripped to keep URL construction predictable.
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
