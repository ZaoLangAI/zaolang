'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { adminApi, setAdminToken } from '@/lib/api/admin-client';
import { highestRole, type AdminRole } from '@/lib/admin/rbac';

export interface AdminSession {
  user_id: string;
  email: string;
  roles: string[];
  max_role: string;
  access_token: string;
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
 * The token is put into the admin client on mount so client-side writes carry
 * it explicitly, rather than relying on the cookie alone: the API treats the
 * bearer token as the credential and the cookie only as its transport.
 */
export function AdminSessionProvider({
  session,
  children,
}: {
  session: AdminSession;
  children: React.ReactNode;
}) {
  const [current] = useState(session);

  useEffect(() => {
    setAdminToken(current.access_token);
    return () => setAdminToken(null);
  }, [current.access_token]);

  const signOut = useCallback(async () => {
    await adminApi.post('/v1/admin/auth/logout');
    setAdminToken(null);
    window.location.assign(`${window.location.pathname.split('/admin')[0]}/admin/login`);
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
