import { type ReactNode } from 'react';

import { type DomainConfig } from '../../data/mockData';
import { useFetch } from '../../hooks/useFetch';
import ActivityFeedSection from './ActivityFeedSection';
import AgentsSection from './AgentsSection';
import ApplicationsSection from './ApplicationsSection';
import DomainHeader from './DomainHeader';
import styles from './DomainPage.module.css';

// Only the domains actually routed through this shared template (see
// App.tsx) — every other slug has a bespoke page or ComingSoonPage. A plain
// `string` would let a mistyped slug fail at runtime as a 404 from
// GET /api/v1/domains/{slug}; the union makes it a compile-time error.
export type GenericDomainSlug = 'finance' | 'stocks';

export interface DomainPageProps {
  slug: GenericDomainSlug;
  children?: ReactNode;
}

export default function DomainPage({ slug, children }: DomainPageProps) {
  const { data: domain, isLoading, error } = useFetch<DomainConfig>(`/api/v1/domains/${slug}`);

  if (error) return <div className={styles.page}>Failed to load domain "{slug}": {error.message}</div>;
  if (isLoading || !domain) return <div className={styles.page}>Loading {slug}…</div>;

  return (
    <div className={styles.page}>
      <DomainHeader domain={domain} />
      <ApplicationsSection applications={domain.applications} />
      <AgentsSection agents={domain.agents} />
      <ActivityFeedSection feed={domain.feed} />
      {children}
    </div>
  );
}
