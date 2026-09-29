'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useState } from 'react';

import { Poster } from '@/components/media/poster';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import * as editorApi from '@/features/editor/api';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { Draft, Page } from '@/lib/api/types';
import { draftDisplayTitle } from '@/lib/draft-title';
import { isVideoCreationOperation } from '@/lib/video-draft';

/**
 * Episode-panel picker for a standalone video-creation draft that was never
 * jumped out of 文案创作. Lists unpublished video drafts with an output,
 * minus anything already linked to this episode.
 */
export function AttachGeneratedVideoDialog({
  open,
  onClose,
  episodeId,
  linkedDraftIds,
  onAttached,
}: {
  open: boolean;
  onClose: () => void;
  episodeId: string;
  linkedDraftIds: Set<string>;
  onAttached: () => void;
}) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const tStates = useTranslations('states');

  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [loading, setLoading] = useState(false);
  const [attachingId, setAttachingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset on each open, adjusted during render rather than in the fetch
  // effect (same pattern as `command-palette.tsx`).
  const [wasOpen, setWasOpen] = useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setError(null);
      setLoading(true);
    }
  }

  useEffect(() => {
    if (!open) return;
    void api
      .get<Page<Draft>>('/v1/drafts')
      .then((page) => setDrafts(page.items))
      .catch((caught) => {
        setError(isApiError(caught) ? caught.message : tStates('errorHint'));
      })
      .finally(() => setLoading(false));
  }, [open, tStates]);

  const candidates = useMemo(
    () =>
      drafts.filter((draft) => {
        if (linkedDraftIds.has(draft.id)) return false;
        if (!draft.output_asset_id) return false;
        return isVideoCreationOperation(draft.params?.operation);
      }),
    [drafts, linkedDraftIds],
  );

  const attach = async (draftId: string) => {
    setAttachingId(draftId);
    setError(null);
    try {
      await editorApi.createContentLink(episodeId, {
        content_type: 'draft',
        content_ref_id: draftId,
        role: 'candidate',
      });
      onAttached();
      onClose();
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : tStates('errorHint'));
    } finally {
      setAttachingId(null);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('addExistingVideo')}
      description={t('addExistingVideoHint')}
      size="lg"
      footer={
        <Button variant="ghost" onClick={onClose} disabled={attachingId !== null}>
          {tActions('cancel')}
        </Button>
      }
    >
      {error ? <ErrorNotice title={error} /> : null}
      {loading ? (
        <div className="grid place-items-center py-8">
          <Spinner className="size-6 text-muted" />
        </div>
      ) : candidates.length === 0 ? (
        <p className="text-sm text-muted">{t('addExistingVideoEmpty')}</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {candidates.map((draft) => {
            const label = draftDisplayTitle(draft, t('contentTypeDraft'));
            return (
              <li key={draft.id}>
                <button
                  type="button"
                  disabled={attachingId !== null}
                  onClick={() => void attach(draft.id)}
                  className="group flex w-full flex-col overflow-hidden rounded-[var(--radius-md)] border border-border text-left transition-colors hover:border-border-strong focus-visible:outline-2 disabled:opacity-60"
                >
                  <Poster
                    src={draft.output_media_type === 'audio' ? null : draft.output_url}
                    alt={label}
                    mediaType={draft.output_media_type}
                    aspect="video"
                    className="rounded-none"
                    lazy
                  />
                  <span className="truncate px-3 py-2 text-xs text-text">
                    {attachingId === draft.id ? tStates('loading') : label}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Dialog>
  );
}
