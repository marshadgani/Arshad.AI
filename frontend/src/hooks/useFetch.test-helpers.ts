import type { UseFetchResult, UseFetchStatus } from './useFetch';

function deriveStatus(isLoading: boolean, error: Error | null, data: unknown): UseFetchStatus {
  if (isLoading) return 'loading';
  if (error) return 'error';
  if (data !== null) return 'success';
  return 'idle';
}

/**
 * Builds a fake useFetch return value for tests that mock the hook.
 *
 * Exists so `status` is derived from the other three fields by the same
 * rule the real hook uses, in one place. Hand-written literals at each
 * mock site either omit `status` (a type error the moment the real shape
 * grows a field) or set it inconsistently with `isLoading`/`error`, which
 * quietly tests a state the hook can never actually produce.
 */
export function fetchResult<T>(overrides: Partial<UseFetchResult<T>> = {}): UseFetchResult<T> {
  const data = overrides.data ?? null;
  const isLoading = overrides.isLoading ?? false;
  const error = overrides.error ?? null;

  return {
    data,
    isLoading,
    error,
    status: overrides.status ?? deriveStatus(isLoading, error, data),
    refetch: overrides.refetch ?? (() => {}),
  };
}
