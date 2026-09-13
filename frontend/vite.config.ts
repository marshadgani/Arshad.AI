/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      // No `rewrite`: every backend router already self-prefixes with
      // /api/v1 (e.g. APIRouter(prefix="/api/v1/auth")), so stripping /api
      // here proxies to /v1/... and 404s every relative API call in dev.
      // vercel.json's prod rewrite preserves the prefix for the same reason.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
    css: true,
  },
});
