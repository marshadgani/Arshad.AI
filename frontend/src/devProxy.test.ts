/**
 * Pins the dev-server API proxy to the prefix the backend actually serves.
 *
 * Every backend router self-prefixes with /api/v1 (APIRouter(prefix="/api/v1/auth"),
 * "/api/v1/dashboard", ...). A `rewrite` that strips /api therefore proxies
 * /api/v1/auth/me to /v1/auth/me and 404s every relative API call in local dev —
 * which previously made the OAuth login flow look half-broken after the callback,
 * because fetchCurrentUser could never load the user.
 *
 * The config is asserted as source text rather than imported: importing
 * vite.config.ts loads vite/esbuild's native binary into the jsdom test runtime,
 * which esbuild refuses to do. This is config with no other coverage, so without
 * this test the mistake is only discoverable by running the stack by hand.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

// Resolved from the project root rather than import.meta.url: under the jsdom
// environment import.meta.url is an http:// URL, which fileURLToPath rejects.
const configSource = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf8');

describe('vite dev server /api proxy', () => {
  it('targets the local backend', () => {
    expect(configSource).toMatch(/target:\s*'http:\/\/localhost:8000'/);
  });

  it('preserves the /api prefix — a rewrite that strips it 404s every backend route', () => {
    // Any `rewrite:` in the proxy block re-opens the prefix-stripping bug; the
    // backend serves the paths the browser already requests, untouched.
    const proxyBlock = configSource.slice(
      configSource.indexOf('proxy:'),
      configSource.indexOf('test:'),
    );

    expect(proxyBlock).toContain("'/api'");
    expect(proxyBlock).not.toMatch(/rewrite\s*:/);
  });
});
