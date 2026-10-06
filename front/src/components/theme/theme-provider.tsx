'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
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

/**
 * 是否应该跳过 View Transition，直接硬切。
 *
 * 覆盖四种情况：浏览器不支持该 API（如 Firefox）、应用内"减少动态效果"开关、
 * OS 级 `prefers-reduced-motion`、文档当前不可见。任意一种为真都不触发转场，
 * 从而不产生 `::view-transition-*` 伪元素——这比事后用 CSS 覆盖它们更简单可靠。
 *
 * 可见性检查是必须的：`document.startViewTransition()` 在文档
 * `visibilityState !== 'visible'` 时会同步抛出 `InvalidStateError`（而不是
 * 优雅地跳过），而不可见并不罕见——后台标签页完成挂载、被预渲染、或者标签页
 * 切走后系统主题才变化，都会落到这个分支上。
 */
function shouldSkipViewTransition(reduceMotion: boolean): boolean {
  if (!('startViewTransition' in document)) return true;
  if (reduceMotion) return true;
  if (document.visibilityState !== 'visible') return true;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
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
  const appliedThemeRef = useRef<ResolvedTheme | null>(null);

  useEffect(() => {
    // 首次挂载时 `<html>` 已经是服务端渲染好的目标主题，直接落地即可，
    // 不需要（也不应该）对着同一个状态放一次转场动画。按"上次落地的主题"
    // 而不是"是否挂载过"来判断：StrictMode 下 effect 会在挂载后重跑一次，
    // 只切换 reduceMotion 也会重跑，这些情况主题都没变，同样不该放转场。
    if (appliedThemeRef.current === null || appliedThemeRef.current === resolved) {
      appliedThemeRef.current = resolved;
      applyToDocument(resolved);
      return;
    }
    appliedThemeRef.current = resolved;

    if (shouldSkipViewTransition(reduceMotion)) {
      applyToDocument(resolved);
      return;
    }

    // 上一次转场还没结束时再开一次，浏览器会跳过前一次（它的更新回调照常执行，
    // 最终主题仍以最后一次为准），但被跳过的那次 `ready` / `updateCallbackDone`
    // 会以 `InvalidStateError: Transition was skipped` reject。没人 await 它们，
    // 不接住就会变成未处理的 rejection，所以这里显式吞掉。
    const transition = document.startViewTransition(() => applyToDocument(resolved));
    transition.ready.catch(() => {});
    transition.updateCallbackDone.catch(() => {});
  }, [resolved, reduceMotion]);

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
