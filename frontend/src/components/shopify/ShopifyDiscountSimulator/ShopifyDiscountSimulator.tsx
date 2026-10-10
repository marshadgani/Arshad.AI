import { useEffect, useId, useState, type FormEvent } from 'react';

import { useShopifyDiscountSimulator } from '../../../hooks/useShopifyDiscountSimulator';
import type { DiscountSimulatorResult } from '../../../types/shopify';
import styles from './ShopifyDiscountSimulator.module.css';

export interface ShopifyDiscountSimulatorProps {
  onResult?: (result: DiscountSimulatorResult) => void;
}

function Outcome({ result }: { result: DiscountSimulatorResult }) {
  if (result.needs_reauth) {
    return <p className={styles.caveat} role="status">Reconnect Shopify to run this check.</p>;
  }
  if (!result.connected) {
    return <p className={styles.caveat} role="status">Shopify is not connected.</p>;
  }
  if (result.partial_failures.length > 0) {
    return (
      <p className={styles.caveat} role="status">
        Shopify could not be reached for this variant. Try again shortly.
      </p>
    );
  }
  if (!result.variant_found) {
    return <p className={styles.caveat} role="status">{result.reason}</p>;
  }
  if (result.valid === null || result.cost_unavailable) {
    return (
      <p className={styles.caveat} role="status">
        Cost unavailable for this variant, so break-even cannot be checked. Add a unit cost in
        Shopify to enable this check.
      </p>
    );
  }
  if (result.valid) {
    return (
      <p className={styles.valid} role="status">
        Margin OK — {result.margin_remaining} remaining per unit after discount
        (price {result.discounted_price}, cost {result.unit_cost}).
      </p>
    );
  }
  return (
    <p className={styles.invalid} role="status">
      {result.reason} Maximum safe discount: {result.max_safe_discount_pct}%.
    </p>
  );
}

export function ShopifyDiscountSimulator({ onResult }: ShopifyDiscountSimulatorProps) {
  const { result, isLoading, error, fieldErrors, checkDiscount } = useShopifyDiscountSimulator();
  const [variantId, setVariantId] = useState('');
  const [percent, setPercent] = useState('');
  const [localErrors, setLocalErrors] = useState<{ variant?: string; percent?: string }>({});
  const idBase = useId();
  const variantInputId = `${idBase}-variant`;
  const percentInputId = `${idBase}-percent`;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = variantId.trim();
    const value = Number(percent);
    const next: { variant?: string; percent?: string } = {};
    if (!trimmed) next.variant = 'Enter a variant ID.';
    if (percent.trim() === '' || !Number.isFinite(value) || value < 0 || value > 100) {
      next.percent = 'Enter a percentage between 0 and 100.';
    }
    setLocalErrors(next);
    if (next.variant || next.percent) return;
    await checkDiscount(trimmed, value);
  }

  useEffect(() => {
    if (result && onResult) onResult(result);
    // onResult is intentionally not a dependency: an inline callback would
    // re-fire for the same result on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  const variantError = localErrors.variant ?? fieldErrors.variant_id;
  const percentError = localErrors.percent ?? fieldErrors.discount_percent;

  return (
    <section className={styles.card} aria-labelledby="discount-sim-title">
      <h2 id="discount-sim-title" className={styles.title}>Discount simulator</h2>
      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <div className={styles.field}>
          <label htmlFor={variantInputId}>Variant ID</label>
          <input
            id={variantInputId}
            type="text"
            value={variantId}
            onChange={(e) => setVariantId(e.target.value)}
            placeholder="gid://shopify/ProductVariant/123"
            aria-invalid={variantError ? true : undefined}
            aria-describedby={variantError ? `${variantInputId}-err` : undefined}
          />
          {variantError && (
            <span id={`${variantInputId}-err`} className={styles.fieldError} role="alert">
              {variantError}
            </span>
          )}
        </div>
        <div className={styles.field}>
          <label htmlFor={percentInputId}>Discount %</label>
          <input
            id={percentInputId}
            type="number"
            inputMode="decimal"
            min={0}
            max={100}
            step="any"
            value={percent}
            onChange={(e) => setPercent(e.target.value)}
            aria-invalid={percentError ? true : undefined}
            aria-describedby={percentError ? `${percentInputId}-err` : undefined}
          />
          {percentError && (
            <span id={`${percentInputId}-err`} className={styles.fieldError} role="alert">
              {percentError}
            </span>
          )}
        </div>
        <button type="submit" className={styles.submit} disabled={isLoading}>
          {isLoading ? 'Checking…' : 'Check discount'}
        </button>
      </form>
      {error && (
        <p className={styles.invalid} role="alert">
          Could not run the check: {error.message}
        </p>
      )}
      {result && <Outcome result={result} />}
    </section>
  );
}
