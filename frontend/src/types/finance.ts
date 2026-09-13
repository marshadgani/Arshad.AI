export type BrokerStatus = 'connected' | 'expired' | 'error';

export interface Holding {
  symbol: string;
  qty: number | null;
  ltp: number | null;
  pnl: number | null;
  value: number | null;
}

export interface BrokerHoldings {
  broker: string;
  display_name: string;
  status: BrokerStatus;
  needs_reauth: boolean;
  currency: string;
  holding_count: number;
  truncated: boolean;
  holdings: Holding[];
  last_synced_at: string | null;
  error: string | null;
}

export interface FinanceHoldingsResponse {
  connected: boolean;
  brokers: BrokerHoldings[];
}
