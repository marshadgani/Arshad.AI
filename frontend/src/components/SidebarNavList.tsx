import { NavLink } from 'react-router-dom';

import type { NavItem } from '../data/mockData';
import styles from './SidebarNavList.module.css';

export interface SidebarNavListProps {
  items: readonly NavItem[];
}

function navItemClass({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.item} ${styles.itemActive}` : styles.item;
}

// Renders nav rows and nothing else: no fetching, no section chrome, no
// knowledge of where the items came from. The fetched Workspace list and the
// static Account list (sidebarAccountNav.ts) both render through this one
// path, so a row's markup — and the `end` rule that stops the root link
// matching every route — exists in exactly one place.
export default function SidebarNavList({ items }: SidebarNavListProps) {
  return (
    <>
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.to === '/'} className={navItemClass}>
          <span className={styles.icon} aria-hidden="true">
            {item.icon}
          </span>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </>
  );
}
