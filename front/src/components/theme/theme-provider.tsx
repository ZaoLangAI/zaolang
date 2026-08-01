'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from 'react';

import {
  MOTION_COOKIE,
  THEME_COOKIE,
  type ResolvedTheme,
  type ThemePreference,
  resolveTheme,
  themeColor,
} from '@/lib/theme';

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (next: ThemePreference) => void;
  reduceMotion: boolean;
  setReduceMotion: (next: boolean) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function writeCookie(name: string, value: string): void {
  document.cookie = `${name}=${value}; path=/; max-age=${60 * 60 * 24 * 365}; samesite=lax`;
}

const COLOR_SCHEME_QUERY = '(prefers-color-scheme: dark)';

function subscribeToColorScheme(onChange: () => void): () => void {
  const query = window.matchMedia(COLOR_SCHEME_QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

/**
 * Reads the OS colour scheme as an external store.
 *
 * The media query is not React state — it changes without us — so subscribing
 * to it directly keeps `system` following the OS live, with no effect that
 * would re-render on every mount.
 */
function useSystemPrefersDark(): boolean {
  return useSyncExternalStore(
    subscribeToColorScheme,
    () => window.matchMedia(COLOR_SCHEME_QUERY).matches,
    // Dark is the design baseline, so it is what the server assumes.
    () => true,
  );
}

function applyToDocument(resolved: ResolvedTheme): void {
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themeColor[resolved]);
}

export function ThemeProvider({
  children,
  initialPreference,
  initialReduceMotion,
  onPersist,
}: {
  children: React.ReactNode;
  initialPreference: ThemePreference;
  initialReduceMotion: boolean;
  /** Signed-in users also get the choice stored server-side. */
  onPersist?: (preference: ThemePreference) => void;
}) {
  const [preference, setPreferenceState] = useState<ThemePreference>(initialPreference);
  const [reduceMotion, setReduceMotionState] = useState(initialReduceMotion);
  const systemPrefersDark = useSystemPrefersDark();

  const resolved = resolveTheme(preference, systemPrefersDark);

  useEffect(() => {
    applyToDocument(resolved);
  }, [resolved]);

  useEffect(() => {
    document.documentElement.dataset.reducedMotion = String(reduceMotion);
  }, [reduceMotion]);

  const setPreference = useCallback(
    (next: ThemePreference) => {
      setPreferenceState(next);
      document.documentElement.dataset.themePreference = next;
      writeCookie(THEME_COOKIE, next);
      onPersist?.(next);
    },
    [onPersist],
  );

  const setReduceMotion = useCallback((next: boolean) => {
    setReduceMotionState(next);
    writeCookie(MOTION_COOKIE, String(next));
  }, []);

  const value = useMemo(
    () => ({ preference, resolved, setPreference, reduceMotion, setReduceMotion }),
    [preference, resolved, setPreference, reduceMotion, setReduceMotion],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useTheme must be used inside ThemeProvider');
  return context;
}
