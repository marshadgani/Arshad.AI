/**
 * Provenance of the hand-drawn fund-flow diagram (./mapSvg).
 *
 * Single source of truth for staleness: the revision label in the header and
 * the "last reviewed" caption both read it, so they cannot drift apart. When
 * the diagram is redrawn, bump both fields in the same commit.
 */
export const MAP_META = {
  revision: 'v13',
  lastReviewed: '2026-09-14',
} as const;

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/**
 * Formats a YYYY-MM-DD date for display, locale-independently.
 *
 * Throws on a malformed date rather than rendering "NaN undefined 2026" —
 * a wrong staleness date is worse than a loud failure.
 */
export function formatReviewed(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number);
  if (!(month >= 1 && month <= 12) || !(day >= 1 && day <= 31) || !Number.isInteger(year)) {
    throw new Error(`formatReviewed: "${iso}" is not a valid YYYY-MM-DD date`);
  }
  return `${day} ${MONTHS[month - 1]} ${year}`;
}
