import styles from './FundFlowLegend.module.css';

/** `#rrggbb`-shaped literal — catches the missing-leading-`#` typo at compile time. */
type HexColor = `#${string}`;

/* Colours are duplicated from the hand-authored SVG in `fundFlowDiagram.ts`,
   which has no shared palette to read them from: changing a band colour in
   the diagram means changing it here too. */
const LEGEND: readonly { color: HexColor; label: string }[] = [
  { color: '#f59e0b', label: 'Income Source' },
  { color: '#fb923c', label: 'Vendor' },
  { color: '#00e5a0', label: 'Saudi Bank' },
  { color: '#e879f9', label: 'Exchange' },
  { color: '#a78bfa', label: 'NRE Account' },
  { color: '#818cf8', label: 'NRO Account' },
  { color: '#38bdf8', label: 'Savings Account' },
  { color: '#34d399', label: 'Family' },
  { color: '#f472b6', label: 'Credit Card' },
  { color: '#fbbf24', label: 'Investment' },
  { color: '#a3e635', label: 'Subscription' },
  { color: '#f97316', label: 'Expense' },
];

export default function FundFlowLegend() {
  return (
    <div className={styles.legend}>
      {LEGEND.map(({ color, label }) => (
        <div key={label} className={styles.legendItem}>
          <div className={styles.legendDot} style={{ background: color, color }} />
          {label}
        </div>
      ))}
    </div>
  );
}
