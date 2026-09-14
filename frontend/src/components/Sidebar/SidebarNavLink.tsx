import { NavLink } from 'react-router-dom';

import type { NavItem } from '../../data/mockData';
import styles from './Sidebar.module.css';

export interface SidebarNavLinkProps {
  item: NavItem;
}

function navItemClass({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.item} ${styles.itemActive}` : styles.item;
}

// Only same-origin, absolute in-app paths may be rendered as a destination.
// The Workspace list comes from /api/v1/nav (a DB table), so `to` is data,
// not a literal: a row of "//evil.com" would be passed through by
// react-router as a protocol-relative URL and navigate the user off-site
// (the class of bug behind GHSA-2j2x-hqr9-3h42), and a "https://…" row
// would do the same outright. Rejecting anything that is not a single
// leading slash keeps the sidebar incapable of pointing outside the app,
// whatever ends up in the table.
export function isInternalPath(to: string): boolean {
  return /^\/(?!\/)/.test(to) || to === '/';
}

export default function SidebarNavLink({ item }: SidebarNavLinkProps) {
  if (!isInternalPath(item.to)) return null;

  return (
    // NavLink matches by prefix, so '/' needs `end` or it is active everywhere.
    <NavLink to={item.to} end={item.to === '/'} className={navItemClass}>
      <span className={styles.icon}>{item.icon}</span>
      <span>{item.label}</span>
    </NavLink>
  );
}
