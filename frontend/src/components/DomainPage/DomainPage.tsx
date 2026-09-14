import { type ReactNode } from 'react';

import { type DomainConfig } from '../../data/mockData';
import { useFetch } from '../../hooks/useFetch';
import { ActivityFeed } from './ActivityFeed';
import { AgentList } from './AgentList';
import { ApplicationList } from './ApplicationList';
import { DomainHeader } from './DomainHeader';
import styles from './DomainPage.module.css';

export interface DomainPageProps {
  slug: string;
  children?: ReactNode;
}

/**
 * Generic domain page: fetches one domain's configuration and composes the
 * sections that render it. This file owns the data lifecycle (loading,
 * error, loaded) only — each section owns its own markup and styles, so a
 * change to how agents are displayed cannot disturb applications.
 */
export default function DomainPage({ slug, children }: DomainPageProps) {
  // slug is encoded because this component is reusable: a future caller could
  // pass a routed param, and an un-encoded "../" would retarget the request at
  // a different API path entirely.
  const { data: domain, isLoading, error } = useFetch<DomainConfig>(
    `/api/v1/domains/${encodeURIComponent(slug)}`,
  );

  if (error) return <div className={styles.page}>Failed to load domain "{slug}": {error.message}</div>;
  if (isLoading || !domain) return <div className={styles.page}>Loading {slug}…</div>;

  return (
    <div className={styles.page}>
      <DomainHeader
        slug={domain.slug}
        title={domain.title}
        emoji={domain.emoji}
        tagline={domain.tagline}
        kpis={domain.kpis}
      />
      <ApplicationList applications={domain.applications} />
      <AgentList agents={domain.agents} />
      <ActivityFeed feed={domain.feed} />
      {children}
    </div>
  );
}
