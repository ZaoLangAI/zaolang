'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { EmptyState } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';
import type { ShortformProfile } from '@/lib/api/types';

import * as editorApi from './api';
import { emptyDocument } from './engine/canonical';
import type { CanonicalDocument, EditCommand, ResolvedAsset, TimelineElement } from './engine/ports';
import { EditorGate } from './gate';
import { useEditorUi } from './store';
import { StudioShell } from './studio/studio-shell';
import { useEditorLease } from './use-editor-lease';

export function DramaEditor({ cutId, draftId }: { cutId: string; draftId: string | null }) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const { lease, token } = useEditorLease(cutId);
  const readonly = useEditorUi((state) => state.readonly);
  const selectedIds = useEditorUi((state) => state.selectedIds);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const select = useEditorUi((state) => state.select);
  const [cut, setCut] = useState<editorApi.EpisodeCut | null>(null);
  const [document, setDocument] = useState<CanonicalDocument>(emptyDocument());
  const [profiles, setProfiles] = useState<ShortformProfile[]>([]);
  const [caption, setCaption] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const next = await editorApi.getCut(cutId);
    setCut(next);
    if (next.head?.document) setDocument(next.head.document);
  }, [cutId]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        await reload();
      } catch (error) {
        if (!cancelled) setLoadError(isApiError(error) ? error.message : t('unavailable'));
      }
      const profiles = await editorApi.loadShortformProfiles();
      if (!cancelled) setProfiles(profiles.profiles);
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [reload, t]);

  const apply = async (commands: EditCommand[]) => {
    if (!cut || !lease || !token) return;
    setBusy(true);
    try {
      const revision = await editorApi.applyCommands(cut.id, {
        batchId: crypto.randomUUID(),
        expectedRevisionId: cut.head_revision_id,
        leaseId: lease.id,
        leaseToken: token,
        commands,
      });
      setDocument(revision.document);
      setCut({ ...cut, head_revision_id: revision.id, head: revision });
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const restore = async (revisionId: string) => {
    if (!cut || !lease || !token) return;
    setBusy(true);
    try {
      const revision = await editorApi.restoreRevision(cut.id, {
        revisionId,
        expectedRevisionId: cut.head_revision_id,
        leaseId: lease.id,
        leaseToken: token,
      });
      setDocument(revision.document);
      setCut({ ...cut, head_revision_id: revision.id, head: revision });
      notify(t('historyRestoreSuccess'), 'success');
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const selected = selectedElement(document, selectedIds[0]);
  const disabled = readonly || busy || !token;
  const assetUrls = cut?.head?.asset_urls ?? {};
  // Keyed off the revision id rather than assetUrls itself: asset_urls only
  // ever changes together with the head revision, and the revision id is a
  // stable primitive the memo can depend on directly.
  const assets: ResolvedAsset[] = useMemo(
    () =>
      Object.entries(assetUrls).map(([assetId, url]) => ({
        asset_id: assetId,
        url,
        mime_type: 'video/mp4',
        duration_ticks: null,
        width: null,
        height: null,
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cut?.head?.id],
  );

  if (loadError) {
    return <EmptyState title={t('unavailable')} description={loadError} />;
  }
  if (!cut) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('loading')} />
      </div>
    );
  }

  return (
    <EditorGate>
      <StudioShell
        cutName={cut.name}
        readonly={readonly}
        document={document}
        assets={assets}
        durationTicks={cut.head?.duration_ticks ?? 0}
        disabled={disabled}
        selected={selected}
        selectedIds={selectedIds}
        caption={caption}
        onCaptionChange={setCaption}
        onSelect={(element) => select([element.id])}
        onApply={(commands) => void apply(commands)}
        onDeleteSelected={() => void apply([{ type: 'delete_elements', element_ids: selectedIds }])}
        onSplitAtPlayhead={() => {
          if (!selected) return;
          void apply([{ type: 'split_element', element_id: selected.id, at_ticks: playheadTicks }]);
        }}
        revisionId={cut.head_revision_id}
        draftId={draftId}
        profiles={profiles}
        cutId={cut.id}
        leaseId={lease?.id ?? null}
        leaseToken={token}
        onPlanApplied={() => void reload()}
        onRestore={(revisionId) => void restore(revisionId)}
      />
    </EditorGate>
  );
}

function selectedElement(
  document: CanonicalDocument,
  id: string | undefined,
): TimelineElement | undefined {
  if (!id) return undefined;
  for (const track of document.tracks) {
    const found = track.elements.find((element) => element.id === id);
    if (found) return found;
  }
  return undefined;
}
