import { afterEach, describe, expect, it, vi } from 'vitest';

import { DEV_BACKEND_ORIGIN, buildOAuthLoginUrl, resolveBackendOrigin } from './oauthLoginUrl';

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('buildOAuthLoginUrl', () => {
  it('builds the absolute Google login URL', () => {
    expect(buildOAuthLoginUrl('google', 'https://arshad-ai.onrender.com')).toBe(
      'https://arshad-ai.onrender.com/api/v1/auth/google/login',
    );
  });

  it('builds the absolute GitHub login URL', () => {
    expect(buildOAuthLoginUrl('github', 'https://arshad-ai.onrender.com')).toBe(
      'https://arshad-ai.onrender.com/api/v1/auth/github/login',
    );
  });

  it('strips a trailing slash from baseUrl so no double slash appears', () => {
    expect(buildOAuthLoginUrl('google', 'https://arshad-ai.onrender.com/')).toBe(
      'https://arshad-ai.onrender.com/api/v1/auth/google/login',
    );
  });

  it('throws on an empty or whitespace-only baseUrl', () => {
    expect(() => buildOAuthLoginUrl('google', '')).toThrow(
      'buildOAuthLoginUrl requires a non-empty baseUrl',
    );
    expect(() => buildOAuthLoginUrl('github', '   ')).toThrow(
      'buildOAuthLoginUrl requires a non-empty baseUrl',
    );
  });

  // A bare "/" normalises to nothing, which would emit a RELATIVE path — the
  // precise failure this module exists to prevent.
  it('throws on a slash-only baseUrl rather than emitting a relative path', () => {
    expect(() => buildOAuthLoginUrl('google', '/')).toThrow(
      'buildOAuthLoginUrl requires a non-empty baseUrl',
    );
  });

  it('keeps a sub-path on the base, appending the login path to it', () => {
    expect(buildOAuthLoginUrl('google', 'https://host.example/foo')).toBe(
      'https://host.example/foo/api/v1/auth/google/login',
    );
  });

  // The return value is assigned to window.location.href. A pseudo-scheme
  // there is script execution in the app's own origin, not a navigation to
  // the backend.
  it.each(['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'mailto:a@b.c'])(
    'rejects the non-http(s) scheme %s',
    (base) => {
      expect(() => buildOAuthLoginUrl('google', base)).toThrow(/absolute http\(s\) backend origin/);
    },
  );

  // Every one of these is scheme-less, so the browser would resolve it
  // against the frontend origin — re-creating the cookie-scope bug (and, for
  // the protocol-relative form, pointing the login at an arbitrary host).
  it.each(['/api/v1', 'arshad-ai.onrender.com', '//evil.example'])(
    'rejects the non-absolute baseUrl %s',
    (base) => {
      expect(() => buildOAuthLoginUrl('github', base)).toThrow(/absolute http\(s\) backend origin/);
    },
  );
});

describe('resolveBackendOrigin', () => {
  it('returns the configured backend origin', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://arshad-ai.onrender.com');

    expect(resolveBackendOrigin()).toBe('https://arshad-ai.onrender.com');
  });

  it('trims surrounding whitespace from the configured value', () => {
    vi.stubEnv('VITE_API_BASE_URL', '  https://arshad-ai.onrender.com  ');

    expect(resolveBackendOrigin()).toBe('https://arshad-ai.onrender.com');
  });

  it('falls back to the local backend when unset outside production', () => {
    vi.stubEnv('VITE_API_BASE_URL', '');

    expect(resolveBackendOrigin()).toBe(DEV_BACKEND_ORIGIN);
  });

  it('throws in production when the backend origin is not configured', () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    vi.stubEnv('PROD', true);

    expect(() => resolveBackendOrigin()).toThrow('VITE_API_BASE_URL must be set');
  });

  it('throws in production when the backend origin is plaintext http', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://arshad-ai.onrender.com');
    vi.stubEnv('PROD', true);

    expect(() => resolveBackendOrigin()).toThrow('must use https in production');
  });

  it('allows a plaintext http origin outside production', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000');

    expect(resolveBackendOrigin()).toBe('http://localhost:8000');
  });
});
