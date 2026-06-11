import styles from './TimePeriodFilter.module.css';

export type Period = '1h' | '1d' | '1w' | '1m' | '1y';

export interface TimePeriodFilterProps {
  value: Period;
  onChange: (period: Period) => void;
}

const PERIODS: { value: Period; label: string }[] = [
  { value: '1h', label: '1H' },
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
  { value: '1m', label: '1M' },
  { value: '1y', label: '1Y' },
];

export default function TimePeriodFilter({ value, onChange }: TimePeriodFilterProps) {
  return (
    <div className={styles.filter}>
      {PERIODS.map((p) => (
        <button
          key={p.value}
          type="button"
          className={`${styles.btn} ${value === p.value ? styles.btnActive : ''}`}
          onClick={() => onChange(p.value)}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
