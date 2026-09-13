/**
 * Reads build-time environment variables exposed by Vite (`import.meta.env`).
 *
 * Kept as a single accessor so tests can stub one module instead of
 * `import.meta.env` directly in every suite that needs a backend origin.
 */
export function backendOrigin(): string {
  const raw = import.meta.env.VITE_BACKEND_URL ?? '';
  return raw.replace(/\/+$/, '');
}
