/**
 * Tests for useBrokerSync — the manual "Sync now" hook.
 *
 * Covers:
 *   parallel-fire pattern (Promise.allSettled over all non-reauth brokers)
 *   isSyncing lifecycle (true during in-flight, false after settle)
 *   onSettled always called in finally() regardless of outcome
 *   partial failure: one broker rejects, syncError set, onSettled still fires
 *   total failure: all brokers reject, isSyncing resolves false, syncError set
 *   reauth guard: needs_reauth brokers skipped; syncError surfaced, no fetch
 *   null / empty brokers: syncAll is a no-op
 *
 * Per .claude/rules/frontend.md: no snapshot tests.
 * Network boundary: syncIntegration mocked via jest.spyOn — no real HTTP.
 */
import { act, renderHook } from '@testing-library/react';
import { useBrokerSync } from './useBrokerSync';
import * as integrationsApi from '../api/integrations';
import type { BrokerHoldings } from '../types/finance';

function makeBroker(
  slug: string,
  overrides: Partial<BrokerHoldings> = {},
): BrokerHoldings {
  return {
    broker: slug,
    display_name: slug,
    status: 'connected',
    needs_reauth: false,
    currency: 'INR',
    holding_count: 1,
    truncated: false,
    holdings: [],
    last_synced_at: null,
    error: null,
    ...overrides,
  };
}

describe('useBrokerSync', () => {
  let syncSpy: jest.SpyInstance;

  beforeEach(() => {
    syncSpy = jest.spyOn(integrationsApi, 'syncIntegration');
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('parallel fire pattern', () => {
    it('calls syncIntegration once per non-reauth broker slug', async () => {
      syncSpy.mockResolvedValue(undefined);
      const onSettled = jest.fn();
      const brokers = [makeBroker('upstox'), makeBroker('zerodha_kite')];

      const { result } = renderHook(() => useBrokerSync(brokers, onSettled));

      await act(async () => {
        result.current.syncAll();
      });

      expect(syncSpy).toHaveBeenCalledTimes(2);
      expect(syncSpy).toHaveBeenCalledWith('upstox');
      expect(syncSpy).toHaveBeenCalledWith('zerodha_kite');
    });

    it('fires both requests without waiting for the first to resolve', async () => {
      // Both resolvers are held open; we check call count *before* any resolve.
      const resolvers: Array<() => void> = [];
      syncSpy.mockImplementation(
        () => new Promise<void>((resolve) => resolvers.push(resolve)),
      );
      const onSettled = jest.fn();
      const brokers = [makeBroker('upstox'), makeBroker('zerodha_kite')];

      const { result } = renderHook(() => useBrokerSync(brokers, onSettled));

      act(() => {
        result.current.syncAll();
      });

      // Both calls must be in-flight before either resolves.
      expect(syncSpy).toHaveBeenCalledTimes(2);

      // Clean up: resolve both so the hook's finally() runs.
      await act(async () => {
        resolvers.forEach((r) => r());
      });
    });
  });

  describe('isSyncing lifecycle', () => {
    it('is false before syncAll is called', () => {
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox')], jest.fn()),
      );
      expect(result.current.isSyncing).toBe(false);
    });

    it('becomes true immediately after syncAll is called', () => {
      let resolver!: () => void;
      syncSpy.mockReturnValue(
        new Promise<void>((res) => {
          resolver = res;
        }),
      );
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox')], jest.fn()),
      );

      act(() => {
        result.current.syncAll();
      });
      expect(result.current.isSyncing).toBe(true);

      // Clean up.
      act(() => {
        resolver();
      });
    });

    it('returns to false once all requests have settled (success)', async () => {
      syncSpy.mockResolvedValue(undefined);
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox')], jest.fn()),
      );

      await act(async () => {
        result.current.syncAll();
      });
      expect(result.current.isSyncing).toBe(false);
    });

    it('returns to false once all requests have settled (failure)', async () => {
      syncSpy.mockRejectedValue(new Error('network error'));
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox')], jest.fn()),
      );

      await act(async () => {
        result.current.syncAll();
      });
      expect(result.current.isSyncing).toBe(false);
    });
  });

  describe('onSettled callback', () => {
    it('calls onSettled exactly once after all-success', async () => {
      syncSpy.mockResolvedValue(undefined);
      const onSettled = jest.fn();
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox'), makeBroker('zerodha_kite')], onSettled),
      );

      await act(async () => {
        result.current.syncAll();
      });

      expect(onSettled).toHaveBeenCalledTimes(1);
      expect(result.current.syncError).toBeNull();
    });

    it('still calls onSettled once when one broker fails (partial failure)', async () => {
      syncSpy
        .mockResolvedValueOnce(undefined)
        .mockRejectedValueOnce(new Error('502 Bad Gateway'));
      const onSettled = jest.fn();
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox'), makeBroker('zerodha_kite')], onSettled),
      );

      await act(async () => {
        result.current.syncAll();
      });

      expect(onSettled).toHaveBeenCalledTimes(1);
    });

    it('still calls onSettled once when all brokers fail', async () => {
      syncSpy.mockRejectedValue(new Error('network error'));
      const onSettled = jest.fn();
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox'), makeBroker('zerodha_kite')], onSettled),
      );

      await act(async () => {
        result.current.syncAll();
      });

      expect(onSettled).toHaveBeenCalledTimes(1);
    });
  });

  describe('syncError state', () => {
    it('is null initially', () => {
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox')], jest.fn()),
      );
      expect(result.current.syncError).toBeNull();
    });

    it('remains null after all-success', async () => {
      syncSpy.mockResolvedValue(undefined);
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox')], jest.fn()),
      );

      await act(async () => {
        result.current.syncAll();
      });
      expect(result.current.syncError).toBeNull();
    });

    it('is set with generic user-facing message on partial failure', async () => {
      syncSpy
        .mockResolvedValueOnce(undefined)
        .mockRejectedValueOnce(new Error('500 Internal Server Error'));
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox'), makeBroker('zerodha_kite')], jest.fn()),
      );

      await act(async () => {
        result.current.syncAll();
      });

      expect(result.current.syncError).not.toBeNull();
      expect(result.current.syncError?.message).toMatch(/one or more brokers failed/i);
    });

    it('does not expose the raw upstream error reason in syncError.message', async () => {
      syncSpy.mockRejectedValue(new Error('HTTP 502 from https://api.upstox.com/v2'));
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox')], jest.fn()),
      );

      await act(async () => {
        result.current.syncAll();
      });

      // The hook uses a generic message, not the upstream reason.
      expect(result.current.syncError?.message).not.toMatch(/upstox.com/i);
      expect(result.current.syncError?.message).not.toMatch(/502/i);
    });

    it('is set and syncIntegration is not called when all brokers need reauth', () => {
      const onSettled = jest.fn();
      const brokers = [
        makeBroker('upstox', { needs_reauth: true }),
        makeBroker('zerodha_kite', { needs_reauth: true }),
      ];
      const { result } = renderHook(() => useBrokerSync(brokers, onSettled));

      act(() => {
        result.current.syncAll();
      });

      expect(syncSpy).not.toHaveBeenCalled();
      expect(result.current.syncError).not.toBeNull();
      expect(result.current.syncError?.message).toMatch(/reconnect/i);
    });
  });

  describe('reauth guard — mixed brokers', () => {
    it('syncs connected brokers and skips needs_reauth brokers', async () => {
      syncSpy.mockResolvedValue(undefined);
      const onSettled = jest.fn();
      const brokers = [
        makeBroker('upstox'),
        makeBroker('zerodha_kite', { needs_reauth: true }),
      ];
      const { result } = renderHook(() => useBrokerSync(brokers, onSettled));

      await act(async () => {
        result.current.syncAll();
      });

      expect(syncSpy).toHaveBeenCalledTimes(1);
      expect(syncSpy).toHaveBeenCalledWith('upstox');
      expect(syncSpy).not.toHaveBeenCalledWith('zerodha_kite');
      expect(result.current.syncError).toBeNull();
    });
  });

  describe('edge cases — null / empty brokers', () => {
    it('is a no-op when brokers is null', () => {
      const onSettled = jest.fn();
      const { result } = renderHook(() => useBrokerSync(null, onSettled));

      act(() => {
        result.current.syncAll();
      });

      expect(syncSpy).not.toHaveBeenCalled();
      expect(onSettled).not.toHaveBeenCalled();
      expect(result.current.isSyncing).toBe(false);
    });

    it('is a no-op when brokers list is empty', () => {
      const onSettled = jest.fn();
      const { result } = renderHook(() => useBrokerSync([], onSettled));

      act(() => {
        result.current.syncAll();
      });

      expect(syncSpy).not.toHaveBeenCalled();
      expect(onSettled).not.toHaveBeenCalled();
      expect(result.current.isSyncing).toBe(false);
    });

    it('does not re-enter if syncAll is called while already syncing', async () => {
      let resolver!: () => void;
      syncSpy.mockReturnValue(
        new Promise<void>((res) => {
          resolver = res;
        }),
      );
      const { result } = renderHook(() =>
        useBrokerSync([makeBroker('upstox')], jest.fn()),
      );

      act(() => {
        result.current.syncAll();
      });
      // Call again while in-flight — should be ignored.
      act(() => {
        result.current.syncAll();
      });

      expect(syncSpy).toHaveBeenCalledTimes(1);

      await act(async () => {
        resolver();
      });
    });
  });
});
