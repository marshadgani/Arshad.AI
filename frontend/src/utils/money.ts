/**
 * formatMoney, extracted from utils/shopifyFormat.ts so it can be shared
 * with the finance/brokerage components without importing "shopify"-named
 * modules from an unrelated domain. shopifyFormat.ts re-exports this
 * unchanged so its existing call sites and test mocks keep working.
 */
/**
 * A share/unit count — not a currency, so no symbol and no forced 2dp, but
 * the same em-dash-for-missing convention as formatMoney so a table mixing
 * the two reads consistently. Fractional quantities are real (Kite reports
 * them for some instruments), hence 4 decimal places rather than 0.
 */
export function formatQuantity(qty: number | null | undefined): string {
  if (qty == null) return '—';
  if (Number.isNaN(qty)) return '—';
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(qty);
}

export function formatMoney(
  amount: number | string | null | undefined,
  currency: string | null | undefined,
): string {
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
