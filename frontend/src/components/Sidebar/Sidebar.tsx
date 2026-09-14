import Scrim from '../Scrim';
import type { NavItem } from '../../data/mockData';
import { useFetch } from '../../hooks/useFetch';
import SidebarNavLink from './SidebarNavLink';
import { useSidebarDrawer } from './useSidebarDrawer';
import styles from './Sidebar.module.css';

export interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  overlayMode: boolean;
}

// Static app chrome, so not served by /api/v1/nav. Every entry must
// correspond to a route registered in App.tsx — listing the destinations
// in one place is what stops dead links reappearing here.
const accountNavItems: NavItem[] = [
  { to: '/integrations', label: 'Integrations', icon: '⌗' },
  { to: '/activity-log', label: 'Activity log', icon: '⏱' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
];

export default function Sidebar({ isOpen, onClose, overlayMode }: SidebarProps) {
  const { data: navItems, error: navError } = useFetch<NavItem[]>('/api/v1/nav');
  const { asideRef, isModal, dialogProps } = useSidebarDrawer(isOpen, onClose, overlayMode);

  return (
    <>
      {isModal && <Scrim label="Close navigation" onDismiss={onClose} />}
      <aside
        id="app-sidebar"
        ref={asideRef}
        className={isOpen ? `${styles.sidebar} ${styles.sidebarOpen}` : styles.sidebar}
        {...dialogProps}
      >
        <div className={styles.brand}>
          <span className={styles.brandMark}>A</span>
          <div className={styles.brandText}>
            <strong>Arshad.AI</strong>
            <span>Personal OS</span>
          </div>
        </div>

        <div className={styles.section}>
          <div className={styles.label}>Workspace</div>
          {navError ? (
            // Hiding the failure behind `navItems ?? []` renders an empty
            // Workspace section with no signal that navigation failed to load.
            <div className={styles.navError} role="alert">
              Navigation failed to load.
            </div>
          ) : (
            (navItems ?? []).map((n) => <SidebarNavLink key={n.to} item={n} />)
          )}
        </div>

        <div className={styles.section}>
          <div className={styles.label}>Account</div>
          {accountNavItems.map((n) => (
            <SidebarNavLink key={n.to} item={n} />
          ))}
        </div>

        <div className={styles.footer}>
          <div className={styles.avatar}>A</div>
          <div className={styles.user}>
            <span className={styles.userName}>Arshad</span>
            <span className={styles.userStatus}>online</span>
          </div>
        </div>
      </aside>
    </>
  );
}
