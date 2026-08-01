'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { api, refreshAccessToken, setAccessToken } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Me } from '@/lib/api/types';

/**
 * A protected action the user attempted before signing in.
 *
 * The design requires the action to resume after login rather than dumping the
 * user on a blank page, so the intent is parked here and replayed once a
 * session exists.
 */
export interface PendingAction {
  label: string;
  run: () => void | Promise<void>;
}

interface SessionContextValue {
  user: Me | null;
  status: 'loading' | 'authenticated' | 'anonymous';
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (input: SignUpInput) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  /** Optimistic local patch, e.g. after spending credits. */
  patchUser: (patch: Partial<Me>) => void;
  /** Runs `action` now if signed in, otherwise opens the login dialog. */
  requireAuth: (action: PendingAction) => void;
  loginPrompt: { open: boolean; label?: string };
  openLogin: () => void;
  closeLogin: () => void;
}

export interface SignUpInput {
  email: string;
  password: string;
  display_name: string;
  handle: string;
  region: string;
  locale: string;
  age_confirmed: boolean;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  children,
  initialUser = null,
}: {
  children: React.ReactNode;
  initialUser?: Me | null;
}) {
  const [user, setUser] = useState<Me | null>(initialUser);
  const [status, setStatus] = useState<'loading' | 'authenticated' | 'anonymous'>('loading');
  const [loginPrompt, setLoginPrompt] = useState<{ open: boolean; label?: string }>({
    open: false,
  });
  const pending = useRef<PendingAction | null>(null);

  const loadMe = useCallback(async () => {
    try {
      const me = await api.get<Me>('/v1/auth/me');
      setUser(me);
      setStatus('authenticated');
    } catch (error) {
      if (error instanceof ApiError && error.isAuthRequired) {
        setUser(null);
        setStatus('anonymous');
        return;
      }
      throw error;
    }
  }, []);

  // The access token lives in memory, so a reload always starts by redeeming
  // the refresh cookie. No cookie means anonymous, with no request wasted.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const token = await refreshAccessToken();
      if (cancelled) return;
      if (!token) {
        setStatus('anonymous');
        return;
      }
      await loadMe();
    })();
    return () => {
      cancelled = true;
    };
  }, [loadMe]);

  const finishLogin = useCallback(async (accessToken: string) => {
    setAccessToken(accessToken);
    const me = await api.get<Me>('/v1/auth/me');
    setUser(me);
    setStatus('authenticated');
    setLoginPrompt({ open: false });

    const action = pending.current;
    pending.current = null;
    await action?.run();
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const body = await api.post<{ access_token: string }>(
        '/v1/auth/login',
        { email, password },
        { anonymous: true },
      );
      await finishLogin(body.access_token);
    },
    [finishLogin],
  );

  const signUp = useCallback(
    async (input: SignUpInput) => {
      const body = await api.post<{ access_token: string }>('/v1/auth/register', input, {
        anonymous: true,
      });
      await finishLogin(body.access_token);
    },
    [finishLogin],
  );

  const signOut = useCallback(async () => {
    try {
      await api.post('/v1/auth/logout');
    } finally {
      setAccessToken(null);
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  const requireAuth = useCallback(
    (action: PendingAction) => {
      if (status === 'authenticated') {
        void action.run();
        return;
      }
      pending.current = action;
      setLoginPrompt({ open: true, label: action.label });
    },
    [status],
  );

  const value = useMemo<SessionContextValue>(
    () => ({
      user,
      status,
      signIn,
      signUp,
      signOut,
      refresh: loadMe,
      patchUser: (patch) => setUser((current) => (current ? { ...current, ...patch } : current)),
      requireAuth,
      loginPrompt,
      openLogin: () => setLoginPrompt({ open: true }),
      closeLogin: () => {
        // Abandoning the dialog abandons the intent; replaying it later would
        // surprise the user with an action they no longer remember starting.
        pending.current = null;
        setLoginPrompt({ open: false });
      },
    }),
    [user, status, signIn, signUp, signOut, loadMe, requireAuth, loginPrompt],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession must be used inside SessionProvider');
  return context;
}
