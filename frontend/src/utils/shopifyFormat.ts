import { formatRelativeTime } from './relativeTime';

export function formatMoney(amount: string | null | undefined, currency: string | null | undefined): string {
  if (amount == null) return '—';
  const value = Number(amount);
  if (Number.isNaN(value)) return '—';
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: currency || 'USD',
    }).format(value);
  } catch {
    return `${amount} ${currency ?? ''}`.trim();
  }
}

// Re-exported, not redefined: formatRelativeTime is app-wide (see
// utils/relativeTime). Existing Shopify callers keep their import path.
export { formatRelativeTime };

export function staleLabel(cachedAt: string | null | undefined): string | null {
  if (!cachedAt) return null;
  return `Updated ${formatRelativeTime(cachedAt)}`;
}

/**
 * Header subtitle for the Shopify page. Either part may be missing on a
 * store whose metadata probe never succeeded, so all four combinations are
 * resolved here rather than as nested ternaries inside JSX.
 */
export function shopSubtitle(
  shopName: string | null | undefined,
  timezone: string | null | undefined,
): string | null {
  const today = timezone ? `Today (${timezone})` : null;
  if (!shopName) return today;
  return today ? `${shopName} · ${today}` : shopName;
}
