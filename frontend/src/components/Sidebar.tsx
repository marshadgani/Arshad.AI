import { NavLink } from 'react-router-dom';
import { navItems } from '../data/mockData';
import styles from './Sidebar.module.css';

export interface SidebarProps {}

export default function Sidebar(_: SidebarProps) {
  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.brandMark}>A</span>
        <div className={styles.brandText}>
          <strong>Arshad.AI</strong>
          <span>Personal OS</span>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.label}>Workspace</div>
        {navItems.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === '/'}
            className={({ isActive }) =>
              isActive ? `${styles.item} ${styles.itemActive}` : styles.item
            }
          >
            <span className={styles.icon}>{n.icon}</span>
            <span>{n.label}</span>
          </NavLink>
        ))}
      </div>

      <div className={styles.section}>
        <div className={styles.label}>Account</div>
        <a className={styles.item} href="#"><span className={styles.icon}>⚙</span>Settings</a>
        <a className={styles.item} href="#"><span className={styles.icon}>⌗</span>Integrations</a>
        <a className={styles.item} href="#"><span className={styles.icon}>📜</span>Activity log</a>
      </div>

      <div className={styles.footer}>
        <div className={styles.avatar}>A</div>
        <div className={styles.user}>
          <span className={styles.userName}>Arshad</span>
          <span className={styles.userStatus}>online</span>
        </div>
      </div>
    </aside>
  );
}
