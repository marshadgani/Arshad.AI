import { useEffect, useState } from 'react';

import { clearToken, getToken } from '../auth/tokenStorage';
import { RENDER_VERDICTS, type VerdictResponse } from '../types/render';

export interface UseRenderDeployVerdictResult {
  data: VerdictResponse | null;
  isLoading: boolean;
  error: Error | null;
}

export function useRenderDeployVerdict(
  serviceId: string | null,
  deployId: string | null,
): UseRenderDeployVerdictResult {
  const [data, setData] = useState<VerdictResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    if (!serviceId || !deployId) {
      setIsLoading(false);
      return;
    }
    const controller = new AbortController();
    setIsLoading(true);
    const token = getToken();
    const url =
      `/api/v1/render/services/${encodeURIComponent(serviceId)}` +
      `/deploys/${encodeURIComponent(deployId)}/verdict`;
    fetch(url, {
      signal: controller.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(async (res) => {
        if (res.status === 401) {
          clearToken();
          throw new Error('401 Unauthorized');
        }
        if (res.status === 429) throw new Error('Too many checks. Wait a minute and try again.');
        if (!res.ok) throw new Error(`The check failed (status ${res.status}). Try again shortly.`);
        const body = (await res.json()) as { data?: VerdictResponse } | null;
        const result = body?.data;
        if (!result || !RENDER_VERDICTS.includes(result.verdict)) {
          throw new Error('The server returned an unexpected response.');
        }
        setData(result);
      })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
    return () => controller.abort();
  }, [serviceId, deployId]);

  return { data, isLoading, error };
}
