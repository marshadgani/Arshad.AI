// localStorage is the locked storage decision (Phase C). XSS would expose
// the JWT — accepted because the alternative (HttpOnly cookies) requires
// CSRF token plumbing the SPA-only flow doesn't need yet.

const KEY = 'arshad.ai:jwt';

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  window.localStorage.setItem(KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(KEY);
}
