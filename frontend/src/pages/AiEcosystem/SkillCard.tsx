import styles from './SkillCard.module.css';

/**
 * Mirrors the backend's SkillCategory Literal (backend/src/skills/categories.py)
 * and its DB-level CHECK constraint. Previously typed as plain `string` here
 * and in the API's SkillResponse — nothing stopped a category value the UI
 * doesn't know how to render from round-tripping silently (CATEGORY_LABELS
 * would fall back to the raw string and cat${category} would resolve to no
 * CSS class). Narrowing this to a union makes CATEGORY_LABELS exhaustively
 * checked by the compiler and forces call sites to handle "value not one of
 * the four" as an explicit, typed case (see `asSkillCategory` below) instead
 * of silently.
 */
export type SkillCategory = 'development' | 'security' | 'data' | 'other';

const KNOWN_CATEGORIES: readonly SkillCategory[] = ['development', 'security', 'data', 'other'];

/** Narrows an API-supplied string to SkillCategory, falling back to 'other'
 * for any value outside the known set — defends the UI against a stale
 * client talking to a newer/older API, or a data-layer bug slipping past
 * the backend's own CHECK constraint. */
export function asSkillCategory(value: string): SkillCategory {
  return (KNOWN_CATEGORIES as readonly string[]).includes(value)
    ? (value as SkillCategory)
    : 'other';
}

export interface SkillData {
  skill_name: string;
  display_name: string;
  description: string;
  source_repo: string;
  category: SkillCategory;
}

export interface SkillCardProps {
  skill: SkillData;
  /** Position within the current page — offsets the entrance animation. */
  index?: number;
}

const CATEGORY_LABELS: Record<SkillCategory, string> = {
  development: 'Dev',
  security: 'Security',
  data: 'Data',
  other: 'Other',
};

export default function SkillCard({ skill, index = 0 }: SkillCardProps) {
  const categoryLabel = CATEGORY_LABELS[skill.category];

  return (
    <div className={styles.card} style={{ animationDelay: `${(index % 12) * 30}ms` }}>
      <div className={styles.header}>
        <span className={styles.name}>{skill.display_name}</span>
        <span className={`${styles.categoryPill} ${styles[`cat${skill.category}`]}`}>
          {categoryLabel}
        </span>
      </div>

      <p className={styles.description}>{skill.description}</p>

      <div className={styles.footer}>
        <span className={styles.repoLabel}>from</span>
        <span className={styles.repoBadge}>{skill.source_repo}</span>
      </div>
    </div>
  );
}
