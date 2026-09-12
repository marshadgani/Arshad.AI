import styles from './Scrim.module.css';

export interface ScrimProps {
  /** Accessible name for the dismiss action, e.g. "Close navigation". */
  label: string;
  onDismiss: () => void;
}

// The dimmed, click-to-dismiss backdrop behind a modal surface.
//
// A button rather than a div so the dismiss action is reachable by keyboard
// and announced by assistive tech. Owning it here keeps the overlay
// primitive — and its z-index contract with tokens.css — in one place
// instead of being restated by every component that needs a backdrop.
export default function Scrim({ label, onDismiss }: ScrimProps) {
  return (
    <button type="button" className={styles.scrim} aria-label={label} onClick={onDismiss} />
  );
}
