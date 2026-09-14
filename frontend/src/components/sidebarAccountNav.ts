import type { NavItem } from '../data/mockData';
import { ACTIVITY_LOG_PATH, INTEGRATIONS_PATH, SETTINGS_PATH } from '../routes/paths';

// The Account section is static, app-owned navigation — unlike Workspace,
// which is served by /api/v1/nav. Declaring it as data in the same NavItem
// shape as the fetched list means both lists render through one component,
// adding or removing an account link is a one-line edit here, and Sidebar
// itself no longer needs to know any route literals.
export const ACCOUNT_NAV_ITEMS: readonly NavItem[] = [
  { to: INTEGRATIONS_PATH, label: 'Integrations', icon: '⌗' },
  { to: SETTINGS_PATH, label: 'Settings', icon: '⚙' },
  { to: ACTIVITY_LOG_PATH, label: 'Activity log', icon: '📜' },
];
