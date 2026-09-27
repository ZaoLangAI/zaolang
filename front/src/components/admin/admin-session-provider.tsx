'use client';

import { createContext, useCallback, useContext, useMemo, useState } from 'react';

import { adminApi, redirectToAdminLogin } from '@/lib/api/admin-client';
import { highestRole, type AdminRole } from '@/lib/admin/rbac';

export interface AdminSession {
  user_id: string;
  email: string;
  roles: string[];
  max_role: string;
}

interface AdminSessionContextValue {
  session: AdminSession;
  role: AdminRole;
  signOut: () => Promise<void>;
}

const AdminSessionContext = createContext<AdminSessionContextValue | null>(null);

/**
 * Holds the console session for client components.
 *
 * No token lives here on purpose: the console session is entirely the
 * httpOnly `zl_admin_session` cookie, sent automatically via
 * `credentials: 'include'` (see `admin-client.ts`). `session` itself only
 * ever carries RBAC-display fields (`AdminSessionResponse` has no
 * `access_token` at all) — passing it down as a Server Component prop can't
 * leak the JWT into the page the way returning it here used to.
 */
export function AdminSessionProvider({
  session,
  children,
}: {
  session: AdminSession;
  children: React.ReactNode;
}) {
  const [current] = useState(session);

  const signOut = useCallback(async () => {
    await adminApi.post('/v1/admin/auth/logout');
    redirectToAdminLogin();
  }, []);

  const value = useMemo(
    () => ({ session: current, role: highestRole(current.roles), signOut }),
    [current, signOut],
  );

  return <AdminSessionContext.Provider value={value}>{children}</AdminSessionContext.Provider>;
}

export function useAdminSession(): AdminSessionContextValue {
  const context = useContext(AdminSessionContext);
  if (!context) throw new Error('useAdminSession must be used inside AdminSessionProvider');
  return context;
}
