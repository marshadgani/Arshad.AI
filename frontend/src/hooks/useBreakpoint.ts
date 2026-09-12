import { below } from '../styles/breakpoints';
import { useMediaQuery } from './useMediaQuery';

// Maps this app's named breakpoints onto the generic useMediaQuery
// primitive. Components ask semantic questions ("are we on mobile?") and
// never see a raw media-query string.

export const MOBILE_QUERY = below('mobile');

export function useIsMobile(): boolean {
  return useMediaQuery(MOBILE_QUERY);
}
