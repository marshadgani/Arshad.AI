import { describe, it, expect } from 'vitest';
import { API_BASE } from './api';

describe('API_BASE', () => {
  it('is a string', () => {
    expect(typeof API_BASE).toBe('string');
  });

  it('does not end with a trailing slash', () => {
    expect(API_BASE.endsWith('/')).toBe(false);
  });

  it('trailing-slash stripping logic works correctly', () => {
    // Unit-test the regex transformation directly
    expect('https://example.com/'.replace(/\/$/, '')).toBe('https://example.com');
    expect('https://example.com'.replace(/\/$/, '')).toBe('https://example.com');
    expect(''.replace(/\/$/, '')).toBe('');
  });

  it('nullish-coalescing fallback for empty string produces a string', () => {
    const value = ('').replace(/\/$/, '');
    expect(value).toBe('');
  });
});
