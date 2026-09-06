import { useRef } from 'react';
import { NavLink } from 'react-router-dom';

import type { NavItem } from '../data/mockData';
import { useBodyScrollLock } from '../hooks/useBodyScrollLock';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { useFetch } from '../hooks/useFetch';
import { useFocusReturn } from '../hooks/useFocusReturn';
import { useIsMobile } from '../hooks/useBreakpoint';
import { useOnRouteChange } from '../hooks/useOnRouteChange';
import styles from './Sidebar.module.css';

export interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

function navItemClass({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.item} ${styles.itemActive}` : styles.item;
}

export default function Sidebar({ isOpen, onClose }: SidebarProps) {
  const { data: navItems } = useFetch<NavItem[]>('/api/v1/nav');
  // Below the mobile breakpoint the sidebar is an off-canvas modal drawer;
  // above it, a persistent landmark. Every modal-only behaviour hangs off
  // this one predicate.
  const overlayMode = useIsMobile();
  const asideRef = useRef<HTMLElement>(null);
  const isModal = isOpen && overlayMode;

  useOnRouteChange(() => {
    if (isOpen) onClose();
  });
  useEscapeKey(isModal, onClose);
  useBodyScrollLock(isModal);
  useFocusReturn(overlayMode, isOpen, asideRef);

  // The desktop sidebar is a persistent landmark, not a dialog — dialog
  // semantics only apply while it behaves as a mobile modal overlay.
  const dialogProps = overlayMode
    ? {
        role: 'dialog' as const,
        'aria-modal': true as const,
        'aria-label': 'Main navigation',
        tabIndex: -1,
      }
    : {};

  return (
    <>
      {isModal && (
        <button
          type="button"
          className={styles.scrim}
          aria-label="Close navigation"
          onClick={onClose}
        />
      )}
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
          {(navItems ?? []).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'} className={navItemClass}>
              <span className={styles.icon}>{n.icon}</span>
              <span>{n.label}</span>
            </NavLink>
          ))}
        </div>

        <div className={styles.section}>
          <div className={styles.label}>Account</div>
          <a className={styles.item} href="#"><span className={styles.icon}>⚙</span>Settings</a>
          <NavLink to="/integrations" className={navItemClass}>
            <span className={styles.icon}>⌗</span>Integrations
          </NavLink>
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
    </>
  );
}
