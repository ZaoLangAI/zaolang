'use client';

import { useEffect, useRef, useState } from 'react';

import { isApiError } from '@/lib/api/errors';

import * as editorApi from './api';
import { browserInstanceId } from './browser';
import { useEditorUi } from './store';

const HEARTBEAT_MS = 30_000;

export function useEditorLease(cutId: string) {
  const setReadonly = useEditorUi((state) => state.setReadonly);
  const [lease, setLease] = useState<editorApi.EditorLease | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const leaseRef = useRef<editorApi.EditorLease | null>(null);
  const tokenRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const instanceId = browserInstanceId();

    const acquire = async () => {
      try {
        const next = await editorApi.acquireLease(cutId, instanceId);
        if (cancelled) return;
        leaseRef.current = next;
        if (next.token) {
          tokenRef.current = next.token;
          setToken(next.token);
        }
        setLease(next);
        setReadonly(!tokenRef.current);
      } catch (caught) {
        if (cancelled) return;
        setReadonly(true);
        if (isApiError(caught) && caught.code === 'LEASE_HELD') return;
      }
    };

    void acquire();

    // A hard tab close or crash skips the React unmount cleanup below, so the
    // lease would otherwise sit held until the server's 5-minute expiry.
    const releaseOnUnload = () => {
      const current = leaseRef.current;
      const currentToken = tokenRef.current;
      if (current && currentToken) {
        void editorApi
          .releaseLease(cutId, current.id, currentToken, { keepalive: true })
          .catch(() => undefined);
      }
    };
    window.addEventListener('pagehide', releaseOnUnload);
    window.addEventListener('beforeunload', releaseOnUnload);

    const timer = window.setInterval(async () => {
      const current = leaseRef.current;
      const currentToken = tokenRef.current;
      if (!current || !currentToken) return;
      try {
        const next = await editorApi.heartbeatLease(cutId, current.id, currentToken, instanceId);
        if (cancelled) return;
        leaseRef.current = next;
        setLease(next);
      } catch {
        if (!cancelled) setReadonly(true);
      }
    }, HEARTBEAT_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener('pagehide', releaseOnUnload);
      window.removeEventListener('beforeunload', releaseOnUnload);
      releaseOnUnload();
    };
  }, [cutId, setReadonly]);

  return { lease, token };
}
