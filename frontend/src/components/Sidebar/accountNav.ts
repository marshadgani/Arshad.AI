import type { NavItem } from '../../data/mockData';
import { ACTIVITY_LOG_PATH, INTEGRATIONS_PATH, SETTINGS_PATH } from '../../routes';

// The Account section is static, app-owned navigation — unlike Workspace,
// which is served by /api/v1/nav. Declaring it as data (same NavItem shape
// as the fetched list) instead of hand-written JSX means adding or removing
// an account link is a one-line edit here, and Sidebar.tsx stays a layout
// component that imports no route constants of its own.
export const ACCOUNT_NAV_ITEMS: readonly NavItem[] = [
  { to: INTEGRATIONS_PATH, label: 'Integrations', icon: '⌗' },
  { to: SETTINGS_PATH, label: 'Settings', icon: '⚙' },
  { to: ACTIVITY_LOG_PATH, label: 'Activity log', icon: '📜' },
];
