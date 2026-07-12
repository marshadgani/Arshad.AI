import styles from './SkillCard.module.css';

export interface SkillData {
  skill_name: string;
  display_name: string;
  description: string;
  source_repo: string;
  category: string;
}

export interface SkillCardProps {
  skill: SkillData;
}

const CATEGORY_LABELS: Record<string, string> = {
  development: 'Dev',
  security: 'Security',
  data: 'Data',
  other: 'Other',
};

export default function SkillCard({ skill }: SkillCardProps) {
  const categoryLabel = CATEGORY_LABELS[skill.category] ?? skill.category;

  return (
    <div className={styles.card}>
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
