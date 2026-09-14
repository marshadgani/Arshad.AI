// Coarse "time ago" label shared by every page that lists timestamped
// records (Shopify orders, Activity Log, …). Lives in its own module
// rather than inside a per-integration formatter so a generic page does
// not have to import from an unrelated domain's util to get it.
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return '—';
  if (ms < 60_000) return 'Just now';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}
