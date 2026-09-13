// Moved to utils/money.ts and utils/time.ts respectively so unrelated
// domains (finance/brokerage, GitHub activity) don't need to import from a
// "shopify"-named module. Re-exported here, unchanged, so existing Shopify
// call sites and vi.mock('../utils/shopifyFormat') paths keep working
// untouched. formatRelativeTime is imported (not just re-exported) because
// staleLabel below still calls it in this module's scope.
import { formatRelativeTime } from './time';

export { formatMoney } from './money';
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
