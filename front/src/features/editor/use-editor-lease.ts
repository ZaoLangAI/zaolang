'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { isApiError } from '@/lib/api/errors';

import * as editorApi from './api';
import { browserInstanceId } from './browser';
import { useEditorUi } from './store';

const HEARTBEAT_MS = 30_000;

export function useEditorLease(cutId: string) {
  const setReadonly = useEditorUi((state) => state.setReadonly);
  const [lease, setLease] = useState<editorApi.EditorLease | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [heldByOther, setHeldByOther] = useState(false);
  const [reclaiming, setReclaiming] = useState(false);
  const leaseRef = useRef<editorApi.EditorLease | null>(null);
  const tokenRef = useRef<string | null>(null);

  const applyLease = useCallback(
    (next: editorApi.EditorLease) => {
      leaseRef.current = next;
      if (next.token) {
        tokenRef.current = next.token;
        setToken(next.token);
      } else {
        tokenRef.current = null;
        setToken(null);
      }
      setLease(next);
      setHeldByOther(false);
      setReadonly(!tokenRef.current);
    },
    [setReadonly],
  );

  const failReadonly = useCallback(
    (held: boolean) => {
      leaseRef.current = null;
      tokenRef.current = null;
      setLease(null);
      setToken(null);
      setHeldByOther(held);
      setReadonly(true);
    },
    [setReadonly],
  );

  const reclaim = useCallback(async () => {
    setReclaiming(true);
    try {
      const next = await editorApi.acquireLease(cutId, browserInstanceId());
      applyLease(next);
    } catch (caught) {
      failReadonly(isApiError(caught) && caught.code === 'LEASE_HELD');
    } finally {
      setReclaiming(false);
    }
  }, [applyLease, cutId, failReadonly]);

  useEffect(() => {
    let cancelled = false;
    const instanceId = browserInstanceId();

    const acquire = async () => {
      try {
        const next = await editorApi.acquireLease(cutId, instanceId);
        if (cancelled) {
          // Strict Mode remounts immediately and may already hold a rotated
          // token on this same lease — releasing that would steal it back.
          const remountTookOver =
            leaseRef.current !== null &&
            (leaseRef.current.id !== next.id || tokenRef.current !== next.token);
          if (next.token && !remountTookOver) {
            void editorApi
              .releaseLease(cutId, next.id, next.token, { keepalive: true })
              .catch(() => undefined);
          }
          return;
        }
        applyLease(next);
      } catch (caught) {
        if (cancelled) return;
        failReadonly(isApiError(caught) && caught.code === 'LEASE_HELD');
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
        if (!cancelled) failReadonly(false);
      }
    }, HEARTBEAT_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener('pagehide', releaseOnUnload);
      window.removeEventListener('beforeunload', releaseOnUnload);
      releaseOnUnload();
    };
  }, [applyLease, cutId, failReadonly]);

  return { lease, token, heldByOther, reclaim, reclaiming };
}
