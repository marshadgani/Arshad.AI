import styles from './TopBar.module.css';

export interface TopBarProps {}

export default function TopBar(_: TopBarProps) {
  return (
    <header className={styles.topbar}>
      <div className={styles.capture}>
        <span className={styles.captureIcon}>⌘</span>
        <input
          className={styles.captureInput}
          type="text"
          placeholder='Quick capture — type "log expense ₹420 lunch", "remind me 5 pm", or any thought…'
        />
        <span className={styles.kbd}>⌘ K</span>
      </div>

      <div className={styles.actions}>
        <button className={styles.iconBtn} aria-label="Notifications">
          🔔
          <span className={styles.dot} />
        </button>
        <button className={styles.iconBtn} aria-label="Settings">⚙</button>
        <button className={styles.iconBtn} aria-label="Profile">A</button>
      </div>
    </header>
  );
}
