import { readdirSync, statSync } from 'fs';
import { resolve } from 'path';

// Shared by the static CSS/import guard suites (breakpoints, grid, overflow),
// which each walked src/ with their own copy of this function.
//
// Test-only: it pulls in Node builtins, so nothing rendered in the browser
// may import it.

export const SRC_DIR = resolve(__dirname, '..');

export function findFiles(dir: string, matches: (name: string) => boolean): string[] {
  const files: string[] = [];

  for (const entry of readdirSync(dir)) {
    const fullPath = resolve(dir, entry);
    if (statSync(fullPath).isDirectory()) {
      files.push(...findFiles(fullPath, matches));
    } else if (matches(entry)) {
      files.push(fullPath);
    }
  }

  return files;
}

export function findCssFiles(): string[] {
  return findFiles(SRC_DIR, (name) => name.endsWith('.module.css'));
}

export function relPath(fullPath: string): string {
  return fullPath.slice(SRC_DIR.length + 1);
}
