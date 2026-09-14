import { useCallback, useState } from 'react';

export interface Preferences {
  /** In-app override for reduced motion, independent of the OS-level
   *  `prefers-reduced-motion` media query (some users can't reach that OS
   *  setting, e.g. on a shared or managed device). */
  reducedMotion: boolean;
}

const STORAGE_KEY = 'arshad.ai:preferences';

const DEFAULTS: Preferences = {
  reducedMotion: false,
};

function readStored(): Preferences {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return DEFAULTS;
  }
}

function writeStored(prefs: Preferences): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // Storage unavailable (private-browsing quota, disabled storage, etc.)
    // — the preference just won't survive a reload; it still applies for
    // the rest of this session via React state.
  }
}

// Mirrors prefers-reduced-motion onto the document root as
// [data-motion="reduced"] so globals.css can apply the same universal
// transition/animation kill switch the OS media query already does,
// without duplicating that CSS per-component.
function applyMotionAttribute(reducedMotion: boolean): void {
  document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'auto';
}

export interface UsePreferencesResult {
  preferences: Preferences;
  setPreference: <K extends keyof Preferences>(key: K, value: Preferences[K]) => void;
}

// Local-only settings store. Not a data-fetching hook (no network, no
// { data, isLoading, error } contract) — reads/writes are synchronous.
export function usePreferences(): UsePreferencesResult {
  const [preferences, setPreferences] = useState<Preferences>(() => {
    const initial = readStored();
    applyMotionAttribute(initial.reducedMotion);
    return initial;
  });

  const setPreference = useCallback(<K extends keyof Preferences>(key: K, value: Preferences[K]) => {
    setPreferences((prev) => {
      const next = { ...prev, [key]: value };
      writeStored(next);
      if (key === 'reducedMotion') applyMotionAttribute(value as boolean);
      return next;
    });
  }, []);

  return { preferences, setPreference };
}
