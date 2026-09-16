import styles from './StatusChip.module.css';

export interface StatusChipProps {
  label: string;
}

// Pure presentation. A coloured leading dot plus an uppercase mono label —
// used anywhere the UI needs to honestly flag a section as not-yet-live
// (ComingSoonPage's "Coming soon" pill, FundFlowMap's "Static map" pill).
export default function StatusChip({ label }: StatusChipProps) {
  return (
    <span className={styles.chip}>
      <span className={styles.dot} aria-hidden="true" />
      <span className={styles.label}>{label}</span>
    </span>
  );
}
