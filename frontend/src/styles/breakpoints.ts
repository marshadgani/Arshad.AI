// Single source of truth for breakpoint pixel values.
//
// CSS Modules cannot import TypeScript, so `@media` rules restate these
// numbers. Every such rule carries a marker comment — `/* breakpoints.ts:
// mobile */` or `/* breakpoints.ts: tablet */` — so a single grep finds all
// of them when a value changes here.

export const BREAKPOINTS = {
  mobile: 768,
  tablet: 1024,
} as const;

export type BreakpointName = keyof typeof BREAKPOINTS;

// 0.02px below the breakpoint avoids the sub-pixel gap that plain
// `max-width: 768px` + `min-width: 768px` pairs leave on fractional-DPR
// displays. This is the same convention Bootstrap uses.
export function below(name: BreakpointName): string {
  return `(max-width: ${BREAKPOINTS[name] - 0.02}px)`;
}

export function atLeast(name: BreakpointName): string {
  return `(min-width: ${BREAKPOINTS[name]}px)`;
}
