import { useEffect, useRef } from 'react';
import { NavLink, useLocation } from 'react-router-dom';

import type { NavItem } from '../data/mockData';
import { useFetch } from '../hooks/useFetch';
import { useIsMobile } from '../hooks/useMediaQuery';
import styles from './Sidebar.module.css';

export interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ isOpen, onClose }: SidebarProps) {
  const { data: navItems } = useFetch<NavItem[]>('/api/v1/nav');
  const { pathname } = useLocation();
  const overlayMode = useIsMobile();
  const asideRef = useRef<HTMLElement>(null);
  const priorFocusRef = useRef<Element | null>(null);
  const priorOverflowRef = useRef<string>('');

  // Close the drawer whenever the route changes.
  useEffect(() => {
    if (isOpen) onClose();
    // Only the route should re-trigger this — onClose/isOpen are stable
    // enough per render and including them would close on every toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Escape closes the drawer, but only while it behaves as a modal overlay.
  useEffect(() => {
    if (!isOpen || !overlayMode) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, overlayMode, onClose]);

  // Lock body scroll while the drawer covers the viewport on mobile. The
  // prior value is captured so a desktop resize mid-open doesn't strand it.
  useEffect(() => {
    if (!isOpen || !overlayMode) return;
    priorOverflowRef.current = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = priorOverflowRef.current;
    };
  }, [isOpen, overlayMode]);

  // Modal focus handling: move focus into the drawer on open, return it to
  // whatever triggered the open (the hamburger) on close.
  useEffect(() => {
    if (!overlayMode) return;
    if (isOpen) {
      priorFocusRef.current = document.activeElement;
      asideRef.current?.focus();
    } else if (priorFocusRef.current instanceof HTMLElement) {
      priorFocusRef.current.focus();
    }
  }, [isOpen, overlayMode]);

  // The desktop sidebar is a persistent landmark, not a dialog — dialog
  // semantics only apply while it behaves as a mobile modal overlay.
  const dialogProps = overlayMode
    ? { role: 'dialog' as const, 'aria-modal': true as const, 'aria-label': 'Main navigation', tabIndex: -1 }
    : {};

  return (
    <>
      {overlayMode && isOpen && (
        <button type="button" className={styles.scrim} aria-label="Close navigation" onClick={onClose} />
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
          <NavLink
            to="/integrations"
            className={({ isActive }) =>
              isActive ? `${styles.item} ${styles.itemActive}` : styles.item
            }
          >
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
