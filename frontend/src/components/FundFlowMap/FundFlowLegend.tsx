import styles from './FundFlowLegend.module.css';

/* The twelve band/stroke colours used inside ./mapSvg. Declared as data
   rather than inlined in the markup so the key can be diffed against the
   diagram's bands without scrolling 500 lines of SVG — the two are
   hand-kept in sync. */
const LEGEND = [
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

/** Colour key for the fund-flow diagram. */
export function FundFlowLegend() {
  return (
    <div className={styles.legend}>
      {LEGEND.map(({ color, label }) => (
        <div key={label} className={styles.legendItem}>
          {/* Inline style: the swatch colour is data, not a theme token —
              it must match the stroke colour used inside the diagram. */}
          <div className={styles.legendDot} style={{ background: color }} />
          {label}
        </div>
      ))}
    </div>
  );
}
