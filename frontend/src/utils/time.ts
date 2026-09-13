// Domain-neutral timestamp formatting. formatRelativeTime came from
// shopifyFormat.ts so non-Shopify widgets (e.g. the GitHub activity card)
// need not import from a "shopify"-named module; it is re-exported there
// unchanged, so existing Shopify call sites keep working.

/**
 * Absolute short date-time in the viewer's locale and zone, or null when
 * there is nothing parseable to show. Callers own the surrounding copy
 * (e.g. "as of …") so the wording stays in the component and the parsing
 * stays here.
 *
 * Returns null rather than a placeholder string: a caller that has no
 * timestamp should omit the element, not render an em dash next to a
 * heading.
 */
export function formatShortDateTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    day: 'numeric',
    month: 'short',
  });
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return '—';
  if (ms < 60_000) return 'Just now';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}
