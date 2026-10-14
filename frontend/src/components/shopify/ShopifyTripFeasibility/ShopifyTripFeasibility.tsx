import { useId, useState, type FormEvent } from 'react';

import { useShopifyTripFeasibility } from '../../../hooks/useShopifyTripFeasibility';
import styles from './ShopifyTripFeasibility.module.css';
import { ShopifyTripFeasibilityOutcome } from './ShopifyTripFeasibilityOutcome';

export interface ShopifyTripFeasibilityProps {
  initialStartDate?: string;
  initialEndDate?: string;
}

const MAX_WINDOW_DAYS = 60;
const DAY_MS = 86_400_000;

function windowError(start: string, end: string): string | null {
  if (!start || !end) return 'Choose both a start and an end date.';
  const days = (Date.parse(end) - Date.parse(start)) / DAY_MS + 1;
  if (Number.isNaN(days)) return 'Enter valid dates.';
  if (days < 1) return 'The end date cannot be before the start date.';
  if (days > MAX_WINDOW_DAYS) return `The window can be at most ${MAX_WINDOW_DAYS} days.`;
  return null;
}

export function ShopifyTripFeasibility({
  initialStartDate = '',
  initialEndDate = '',
}: ShopifyTripFeasibilityProps) {
  const { result, isLoading, error, fieldErrors, check } = useShopifyTripFeasibility();
  const [start, setStart] = useState(initialStartDate);
  const [end, setEnd] = useState(initialEndDate);
  const [localError, setLocalError] = useState<string | null>(null);
  const idBase = useId();
  const startId = `${idBase}-start`;
  const endId = `${idBase}-end`;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = windowError(start, end);
    setLocalError(problem);
    if (problem) return;
    await check(start, end);
  }

  const startError = fieldErrors.start_date;
  const endError = localError ?? fieldErrors.end_date;

  return (
    <section className={styles.card} aria-labelledby={`${idBase}-title`}>
      <h2 id={`${idBase}-title`} className={styles.title}>Trip feasibility</h2>
      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <div className={styles.field}>
          <label htmlFor={startId}>Start date</label>
          <input
            id={startId}
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            aria-invalid={startError ? true : undefined}
            aria-describedby={startError ? `${startId}-err` : undefined}
          />
          {startError && (
            <span id={`${startId}-err`} className={styles.fieldError} role="alert">
              {startError}
            </span>
          )}
        </div>
        <div className={styles.field}>
          <label htmlFor={endId}>End date</label>
          <input
            id={endId}
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            aria-invalid={endError ? true : undefined}
            aria-describedby={endError ? `${endId}-err` : undefined}
          />
          {endError && (
            <span id={`${endId}-err`} className={styles.fieldError} role="alert">
              {endError}
            </span>
          )}
        </div>
        <button type="submit" className={styles.submit} disabled={isLoading}>
          {isLoading ? 'Checking…' : 'Check trip'}
        </button>
      </form>
      {error && (
        <p className={styles.caveat} role="alert">
          Could not run the check: {error.message}
        </p>
      )}
      {result && <ShopifyTripFeasibilityOutcome result={result} />}
    </section>
  );
}
