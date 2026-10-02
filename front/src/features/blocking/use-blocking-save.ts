'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { isApiError } from '@/lib/api/errors';

import { patchBlocking } from './api';
import type { BlockingDocument, BlockingState } from './types';

export type SaveStatus = 'idle' | 'pending' | 'saving' | 'saved' | 'error';

const DEBOUNCE_MS = 600;

/**
 * Persists manual 白膜 edits. The caller has already applied an edit to its
 * own state (so the viewport never waits on the network); this debounces a
 * burst of drags into one `PATCH …/blocking`, always sends the *latest*
 * document against the latest known version, and reports a 409 so the
 * studio can reload instead of overwriting a newer chat turn.
 *
 * A save's response only replaces the local document when no newer edit
 * was made while it was in flight — otherwise it just advances the version.
 */
export function useBlockingSave({
  episodeId,
  versionNo,
  onSaved,
  onConflict,
  onError,
}: {
  episodeId: string;
  versionNo: number;
  onSaved: (state: BlockingState) => void;
  onConflict: () => void;
  onError: (message: string) => void;
}) {
  const [status, setStatus] = useState<SaveStatus>('idle');
  const versionRef = useRef(versionNo);
  const pendingRef = useRef<BlockingDocument | null>(null);
  const revisionRef = useRef(0);
  const inflightRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handlersRef = useRef({ onSaved, onConflict, onError });

  useEffect(() => {
    handlersRef.current = { onSaved, onConflict, onError };
  }, [onSaved, onConflict, onError]);

  // A chat turn or rebuild mints a new version outside this hook.
  useEffect(() => {
    versionRef.current = versionNo;
  }, [versionNo]);

  // Drains the queue: an edit made while a save is in flight goes out right
  // after it, against the version that save returned.
  const flush = useCallback(async () => {
    if (inflightRef.current) return;
    inflightRef.current = true;
    try {
      while (pendingRef.current) {
        const document = pendingRef.current;
        const sentRevision = revisionRef.current;
        pendingRef.current = null;
        setStatus('saving');
        try {
          const saved = await patchBlocking(episodeId, document, versionRef.current);
          versionRef.current = saved.version_no;
          if (revisionRef.current === sentRevision) {
            handlersRef.current.onSaved(saved);
            setStatus('saved');
          }
        } catch (error) {
          pendingRef.current = null;
          setStatus('error');
          if (isApiError(error) && error.status === 409) handlersRef.current.onConflict();
          else handlersRef.current.onError(isApiError(error) ? error.message : String(error));
          return;
        }
      }
    } finally {
      inflightRef.current = false;
    }
  }, [episodeId]);

  const schedule = useCallback(
    (document: BlockingDocument) => {
      pendingRef.current = document;
      revisionRef.current += 1;
      setStatus('pending');
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => void flush(), DEBOUNCE_MS);
    },
    [flush],
  );

  // Leaving the page inside the debounce window still saves the last drag.
  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (pendingRef.current) void flush();
    },
    [flush],
  );

  return { status, schedule };
}
