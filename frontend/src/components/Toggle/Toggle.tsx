import styles from './Toggle.module.css';

export interface ToggleProps {
  /** Also used as the underlying button's `id`, so callers can pair a `<label htmlFor>` with it. */
  id: string;
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

// A reusable on/off control. Uses `role="switch"` on a native <button>
// rather than a styled checkbox — screen readers announce "switch,
// on/off" instead of "checkbox, checked/unchecked", which better matches
// an immediate-effect preference (vs. a form field awaiting submit).
export default function Toggle({
  id,
  label,
  description,
  checked,
  onChange,
  disabled = false,
}: ToggleProps) {
  return (
    <div className={styles.row}>
      <div className={styles.text}>
        <label htmlFor={id} className={styles.label}>
          {label}
        </label>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        className={checked ? `${styles.switch} ${styles.switchOn}` : styles.switch}
        onClick={() => onChange(!checked)}
      >
        <span className={styles.thumb} />
      </button>
    </div>
  );
}
