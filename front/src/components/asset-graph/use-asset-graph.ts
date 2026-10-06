'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type {
  AssetEdge,
  AssetEntryType,
  AssetGraph,
  AssetVariant,
  CharacterVoice,
} from '@/lib/api/types';
import { uploadFile } from '@/lib/upload';

import type { CardKind } from '@/components/library/entry-actions';

export interface AssetGraphActions {
  base: string;
  segment: 'looks' | 'variants';
  createVariant: (body: Record<string, unknown>) => Promise<AssetVariant | undefined>;
  updateVariant: (id: string, body: Record<string, unknown>) => Promise<unknown>;
  /** Resolves `true` once deleted, `undefined` on failure (likewise below). */
  deleteVariant: (id: string) => Promise<true | undefined>;
  upload: (variantId: string, file: File, entryType: AssetEntryType) => Promise<unknown>;
  updateEntry: (id: string, body: Record<string, unknown>) => Promise<unknown>;
  deleteEntry: (id: string) => Promise<true | undefined>;
  approveEntry: (id: string) => Promise<unknown>;
  anchorEntry: (id: string) => Promise<unknown>;
  createEdge: (body: Record<string, unknown>) => Promise<AssetEdge | undefined>;
  updateEdge: (id: string, body: Record<string, unknown>) => Promise<unknown>;
  deleteEdge: (id: string) => Promise<true | undefined>;
  createVoice: (body: Record<string, unknown>) => Promise<CharacterVoice | undefined>;
  updateVoice: (id: string, body: Record<string, unknown>) => Promise<CharacterVoice | undefined>;
  deleteVoice: (id: string) => Promise<true | undefined>;
  refresh: () => Promise<void>;
}

/**
 * The card graph and every write on it. Each write refetches `/graph`, so
 * what the canvas, inspector and outline show is always the server's view
 * (no optimistic merge to get wrong). A failure is a toast plus `error` —
 * the write resolves `undefined` and the caller's own UI stays as it was.
 */
export function useAssetGraph(kind: CardKind, initial: AssetGraph) {
  const t = useTranslations('assetGraph');
  const { notify } = useToast();
  const segment = kind === 'character' ? 'looks' : 'variants';
  const api_ = { character: 'characters', scene: 'scenes', prop: 'props' }[kind];
  const base = `/v1/${api_}/${initial.card_id}`;
  const [graph, setGraph] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setGraph(await api.get<AssetGraph>(`${base}/graph`));
  }, [base]);

  const run = useCallback(
    async <T>(work: () => Promise<T>): Promise<T | undefined> => {
      setBusy(true);
      setError(null);
      try {
        const result = await work();
        await refresh();
        return result;
      } catch (caught) {
        const message = caught instanceof ApiError ? caught.message : t('genericError');
        setError(message);
        notify(message, 'error');
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [refresh, notify, t],
  );

  const actions: AssetGraphActions = {
    base,
    segment,
    refresh,
    createVariant: (body) => run(() => api.post<AssetVariant>(`${base}/${segment}`, body)),
    updateVariant: (id, body) => run(() => api.patch(`${base}/${segment}/${id}`, body)),
    deleteVariant: (id) =>
      run(async () => {
        await api.delete(`${base}/${segment}/${id}`);
        return true as const;
      }),
    upload: (variantId, file, entryType) =>
      run(async () => {
        const asset = await uploadFile(file, 'generation_reference');
        await api.post(`${base}/${segment}/${variantId}/entries`, {
          asset_id: asset.id,
          entry_type: entryType,
        });
        notify(t('uploaded'), 'success');
      }),
    updateEntry: (id, body) => run(() => api.patch(`${base}/entries/${id}`, body)),
    deleteEntry: (id) =>
      run(async () => {
        await api.delete(`${base}/entries/${id}`);
        return true as const;
      }),
    approveEntry: (id) => run(() => api.post(`${base}/entries/${id}:approve`)),
    anchorEntry: (id) => run(() => api.post(`${base}/entries/${id}:anchor`)),
    createEdge: (body) => run(() => api.post<AssetEdge>(`${base}/edges`, body)),
    updateEdge: (id, body) => run(() => api.patch(`${base}/edges/${id}`, body)),
    createVoice: (body) => run(() => api.post<CharacterVoice>(`${base}/voices`, body)),
    updateVoice: (id, body) => run(() => api.patch<CharacterVoice>(`${base}/voices/${id}`, body)),
    deleteVoice: (id) =>
      run(async () => {
        await api.delete(`${base}/voices/${id}`);
        return true as const;
      }),
    deleteEdge: (id) =>
      run(async () => {
        await api.delete(`${base}/edges/${id}`);
        return true as const;
      }),
  };

  return { graph, busy, error, actions, clearError: () => setError(null) };
}

export type AssetGraphStore = ReturnType<typeof useAssetGraph>;
