/**
 * Wire types for /api/v1/obsidian/ontology/* (FEAT-141).
 *
 * Mirrors backend/src/api/v1/obsidian.py's ontology_status /
 * list_ontology_entities response bodies. Kept out of the page/hooks so
 * every consumer (panel, list, tests) shares one definition.
 */

export const ONTOLOGY_DOMAINS = ['calendar', 'email', 'github', 'people'] as const;
export type OntologyDomain = (typeof ONTOLOGY_DOMAINS)[number];

export const ONTOLOGY_ENTITY_TYPES = [
  'Person',
  'Event',
  'Thread',
  'Repo',
  'IssuePR',
  'MOC',
] as const;
export type OntologyEntityType = (typeof ONTOLOGY_ENTITY_TYPES)[number];

// pending | synced | deferred | conflict | archived — see models/ontology.py.
export const ONTOLOGY_SYNC_STATES = [
  'pending',
  'synced',
  'deferred',
  'conflict',
  'archived',
] as const;
export type OntologySyncState = (typeof ONTOLOGY_SYNC_STATES)[number];

// running | succeeded | partial | deferred | failed | dry_run
export type OntologyRunStatus =
  | 'running'
  | 'succeeded'
  | 'partial'
  | 'deferred'
  | 'failed'
  | 'dry_run';

export interface OntologyEntity {
  id: string;
  domain: string;
  entity_type: string;
  stable_entity_id: string;
  display_name: string;
  vault_path: string;
  sync_state: string;
  conflict_reason: string | null;
  tags: string[];
  source_updated_at: string | null;
  last_synced_at: string | null;
}

export interface OntologyStatus {
  last_run_at: string | null;
  last_run_status: OntologyRunStatus | null;
  last_commit_sha: string | null;
  branch: string | null;
  entity_counts_by_domain: Record<string, number>;
  total_entities: number;
  deferred: number;
  conflicts: number;
  archived: number;
}

export interface OntologyEntityFilters {
  domain?: string;
  entity_type?: string;
  sync_state?: string;
}

export interface TriggerOntologySyncRequest {
  lookback_days?: number;
  max_entities?: number;
  domains?: string[];
  dry_run?: boolean;
}

export interface TriggerOntologySyncResponse {
  job_id: string;
  status: string;
  deduplicated: boolean;
}
