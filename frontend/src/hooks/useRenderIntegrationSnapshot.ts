import { useEffect, useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';
import type { RenderServicesSnapshot } from '../types/render';

export interface UseRenderIntegrationSnapshotResult {
  data: RenderServicesSnapshot | null;
  isLoading: boolean;
  error: Error | null;
}

export function useRenderIntegrationSnapshot(): UseRenderIntegrationSnapshotResult {
  const [data, setData] = useState<RenderServicesSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const token = getToken();
    fetch('/api/v1/render/services', {
      signal: controller.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(async (res) => {
        if (res.status === 401) {
          clearToken();
          throw new Error('401 Unauthorized');
        }
        if (!res.ok) throw new Error(`Could not load Render services (status ${res.status}).`);
        const body = (await res.json()) as { data?: RenderServicesSnapshot } | null;
        if (!body?.data) throw new Error('The server returned an unexpected response.');
        setData(body.data);
      })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
    return () => controller.abort();
  }, []);

  return { data, isLoading, error };
}
