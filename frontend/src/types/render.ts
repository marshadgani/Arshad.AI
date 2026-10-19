export const RENDER_VERDICTS = ['regression', 'neutral', 'improvement', 'unknown'] as const;
export type RenderVerdict = (typeof RENDER_VERDICTS)[number];

export interface VerdictResponse {
  verdict: RenderVerdict;
  before_error_count: number;
  after_error_count: number;
  before_error_rate: number;
  after_error_rate: number;
  cpu_before_mean: number | null;
  cpu_after_mean: number | null;
  memory_before_mean: number | null;
  memory_after_mean: number | null;
  latency_before_mean: number | null;
  latency_after_mean: number | null;
  connected: boolean;
  needs_reauth: boolean;
  partial_failures: string[];
  log_truncated: boolean;
}

export interface RenderServiceSummary {
  id: string;
  name: string | null;
  latest_deploy_id: string | null;
  latest_deploy_status: string | null;
}

export interface RenderServicesSnapshot {
  connected: boolean;
  needs_reauth: boolean;
  services: RenderServiceSummary[];
}
