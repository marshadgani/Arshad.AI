/**
 * Shared types, constants and narrow utility functions for the OntologyVisibility page.
 *
 * Keeping these in a dedicated module:
 *  - lets the mutation hook and the component import from one authoritative place
 *  - prevents the component from being the ambient type source for tests
 *  - makes the domain vocabulary (Visibility, EntityType) re-exportable from index.ts
 */

export const Visibility = { Public: 'public', Private: 'private' } as const;
export type Visibility = (typeof Visibility)[keyof typeof Visibility];

export const EntityType = { Person: 'person', Project: 'project' } as const;
export type EntityType = (typeof EntityType)[keyof typeof EntityType];

export type EntityItem = Readonly<{
  id: string;
  entity_type: EntityType;
  external_key: string;
  visibility: Visibility;
}>;

export type EntityList = Readonly<{
  entities: readonly EntityItem[];
  total: number;
}>;

/** `''` means "no filter applied"; narrowing happens once at the select boundary. */
export type Filter<T extends string> = T | '';

export function isMember<T extends string>(
  values: Readonly<Record<string, T>>,
  v: string,
): v is T {
  return (Object.values(values) as string[]).includes(v);
}

export function parseFilter<T extends string>(
  values: Readonly<Record<string, T>>,
  v: string,
): Filter<T> {
  return isMember(values, v) ? v : '';
}

export const EXPORT_COMMAND = 'python scripts/obsidian_vault_export.py';
export const VAULT_REPO = 'marshadgani/Arshad-Ideaverse';
