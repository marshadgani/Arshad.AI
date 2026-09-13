import type { DomainComingSoonProps } from '../components/DomainComingSoon';

// `satisfies` (not a `:` annotation) type-checks every entry while keeping the
// keys literal, so a typo'd lookup in a page is a compile error rather than an
// `undefined` spread at runtime.
export const COMING_SOON_DOMAINS = {
  'home-iot': {
    emoji: '🏠',
    title: 'Home & IoT',
    reason:
      'No smart-home or device provider is connected. Arshad.AI has no Home & IoT integration built yet, so there is nothing real to show here.',
  },
  learning: {
    emoji: '📚',
    title: 'Learning · Second Brain',
    reason:
      'Notion and Todoist can be connected on the Integrations page, but no Learning dashboard is built on top of them yet.',
  },
  travel: {
    emoji: '✈️',
    title: 'Travel',
    reason:
      'No flight, hotel, or booking provider is connected. Arshad.AI has no Travel integration built yet, so there is nothing real to show here.',
  },
} as const satisfies Record<string, DomainComingSoonProps>;
