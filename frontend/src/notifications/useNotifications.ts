import { useState } from 'react';

import { type Notification } from '../data/mockData';
import { useFetch, type UseFetchResult } from '../hooks/useFetch';

/**
 * Single declaration of where notifications come from. The URL was
 * previously written out at two unrelated call sites (the TopBar panel and
 * the dashboard widget's data hook), so a route change had to be found
 * twice by grep.
 */
export const NOTIFICATIONS_ENDPOINT = '/api/v1/dashboard/notifications';

/**
 * Notifications for a surface that is not always visible.
 *
 * `isActive` is latched, never unlatched: nothing is requested until the
 * surface is opened for the first time, so TopBar — mounted on every
 * route — costs zero requests on page load and zero per navigation, and
 * reopening reuses the data already fetched rather than refetching on
 * every open.
 *
 * The latch lives here rather than in the panel because it is a property
 * of how this data is loaded, not of how it is drawn; the panel is left
 * as a pure rendering of { data, isLoading, error, refetch }.
 */
export function useNotifications(isActive: boolean): UseFetchResult<Notification[]> {
  const [hasEverBeenActive, setHasEverBeenActive] = useState(false);
  if (isActive && !hasEverBeenActive) setHasEverBeenActive(true);

  return useFetch<Notification[]>(NOTIFICATIONS_ENDPOINT, { skip: !hasEverBeenActive });
}
