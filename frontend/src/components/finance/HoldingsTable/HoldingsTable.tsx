import { formatMoney, formatQuantity } from '../../../utils/money';
import type { Holding } from '../../../types/finance';
import styles from './HoldingsTable.module.css';

export interface HoldingsTableProps {
  holdings: Holding[];
  currency: string;
  holdingCount: number;
  truncated: boolean;
}

/** The em dash is labelled so a screen reader announces "no data" rather
 * than reading the punctuation, or nothing at all. */
function noData() {
  return <span aria-label="no data">—</span>;
}

/** The one cell renderer that is markup, not formatting — hence not in utils. */
function moneyCell(value: number | null, currency: string) {
  if (value == null) {
    return noData();
  }
  return formatMoney(value, currency);
}

function pnlTone(value: number): string | undefined {
  if (value > 0) {
    return styles.pnlUp;
  }
  if (value < 0) {
    return styles.pnlDown;
  }
  return undefined;
}

/** Colour-codes P&amp;L without ever relying on colour alone: the sign is
 * already present in formatMoney's output, this only adds emphasis. */
function pnlCell(value: number | null, currency: string) {
  if (value == null) {
    return noData();
  }
  return <span className={pnlTone(value)}>{formatMoney(value, currency)}</span>;
}

/**
 * Both Upstox and Zerodha cap the holdings they store at 10 rows (see
 * backend/src/integrations/personal/{upstox,zerodha_kite}.py). A portfolio
 * total computed here would be confidently wrong whenever `truncated` is
 * true, so this table deliberately never renders one.
 */
export function HoldingsTable({ holdings, currency, holdingCount, truncated }: HoldingsTableProps) {
  const showPnl = holdings.some((h) => h.pnl !== null);

  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col" className={styles.symbol}>
              Symbol
            </th>
            <th scope="col" className={styles.numeric}>
              Qty
            </th>
            <th scope="col" className={styles.numeric}>
              LTP
            </th>
            {showPnl && (
              <th scope="col" className={styles.numeric}>
                P&amp;L
              </th>
            )}
            <th scope="col" className={styles.numeric}>
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((h, i) => (
            <tr key={`${h.symbol}-${i}`}>
              <td className={styles.symbol}>{h.symbol}</td>
              <td className={styles.numeric}>{formatQuantity(h.qty)}</td>
              <td className={styles.numeric}>{moneyCell(h.ltp, currency)}</td>
              {showPnl && <td className={styles.numeric}>{pnlCell(h.pnl, currency)}</td>}
              <td className={styles.numeric}>{moneyCell(h.value, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && (
        <p className={styles.caption}>
          Showing top {holdings.length} of {holdingCount} holdings
        </p>
      )}
    </div>
  );
}
