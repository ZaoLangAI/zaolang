'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Button, IconButton } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextInput } from '@/components/ui/field';
import { IconClose, IconPlus, IconUser } from '@/components/ui/icons';
import { Badge, ErrorNotice, SectionHeading } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { useToast } from '@/components/ui/toast';
import { Avatar } from '@/components/work/avatar';
import * as editorApi from '@/features/editor/api';
import { isApiError } from '@/lib/api/errors';

const MAX_COLLABORATORS = 20;

/**
 * "共创成员" section on the series detail page. Owner-only invite/remove
 * controls; a collaborator only sees the roster plus a "退出共创" action on
 * their own row. Never rendered for the timeline editor/trash/publish
 * surfaces — those stay owner-only regardless of collaboration state (see
 * `zaolang-editor-drama`).
 */
export function CollaboratorsPanel({
  series,
  onChanged,
}: {
  series: editorApi.DramaSeries;
  onChanged?: () => void;
}) {
  const t = useTranslations('editor');
  const { user } = useSession();
  const { notify } = useToast();

  const [rows, setRows] = useState<editorApi.SeriesCollaborator[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [identifier, setIdentifier] = useState('');
  const [inviting, setInviting] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  const isOwner = series.viewer_role === 'owner';
  const currentUserId = user?.id;

  const load = () => {
    void editorApi
      .listCollaborators(series.id)
      .then((items) => {
        setRows(items);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series.id]);

  const invite = async () => {
    const cleaned = identifier.trim();
    if (!cleaned) return;
    setInviting(true);
    setInviteError(null);
    try {
      const row = await editorApi.inviteCollaborator(series.id, cleaned);
      setRows((current) => [...current, row]);
      setIdentifier('');
      setInviteOpen(false);
      notify(t('inviteCollaboratorSent'), 'success');
      onChanged?.();
    } catch (error: unknown) {
      setInviteError(isApiError(error) ? error.message : t('commandFailed'));
    } finally {
      setInviting(false);
    }
  };

  const closeInviteDialog = () => {
    setInviteOpen(false);
    setInviteError(null);
    setIdentifier('');
  };

  const remove = (row: editorApi.SeriesCollaborator) => {
    setRemovingId(row.id);
    void editorApi
      .removeCollaborator(series.id, row.id)
      .then(() => {
        setRows((current) => current.filter((item) => item.id !== row.id));
        notify(
          row.user_id === currentUserId
            ? t('leaveCollaborationDone')
            : t('removeCollaboratorDone'),
          'success',
        );
        onChanged?.();
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setRemovingId(null));
  };

  const atLimit = rows.length >= MAX_COLLABORATORS;

  return (
    <section>
      <SectionHeading
        title={t('collaboratorsPanelTitle')}
        description={t('collaboratorsCountLabel', { count: rows.length, max: MAX_COLLABORATORS })}
        action={
          isOwner ? (
            <Button
              size="sm"
              icon={<IconPlus className="size-3.5" />}
              disabled={atLimit}
              title={atLimit ? t('collaboratorLimitReachedHint') : undefined}
              onClick={() => setInviteOpen(true)}
            >
              {t('inviteCollaboratorAction')}
            </Button>
          ) : undefined
        }
      />

      {!loaded ? (
        <div className="flex justify-center py-6">
          <Spinner />
        </div>
      ) : rows.length === 0 ? (
        <p className="rounded-[var(--radius-md)] border border-dashed border-border px-4 py-6 text-center text-sm text-muted">
          {t('collaboratorsEmpty')}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => {
            const isSelf = row.user_id === currentUserId;
            const canRemove = isOwner || isSelf;
            return (
              <li
                key={row.id}
                className="flex items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-3 py-2.5"
              >
                <Avatar src={row.avatar_url} name={row.display_name} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{row.display_name}</p>
                  <p className="truncate text-xs text-muted">@{row.handle}</p>
                </div>
                {row.status === 'pending' ? (
                  <Badge tone="amber">{t('collaboratorStatusPending')}</Badge>
                ) : null}
                {canRemove ? (
                  <IconButton
                    label={isSelf ? t('leaveCollaborationAction') : t('removeCollaboratorAction')}
                    variant="ghost"
                    size="sm"
                    loading={removingId === row.id}
                    onClick={() => remove(row)}
                  >
                    <IconClose className="size-4" />
                  </IconButton>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <Dialog
        open={inviteOpen}
        onClose={closeInviteDialog}
        title={t('inviteCollaboratorAction')}
        size="sm"
        footer={
          <>
            <Button variant="ghost" size="sm" disabled={inviting} onClick={closeInviteDialog}>
              {t('inviteCollaboratorCancel')}
            </Button>
            <Button
              size="sm"
              icon={<IconUser className="size-3.5" />}
              loading={inviting}
              disabled={!identifier.trim()}
              onClick={() => void invite()}
            >
              {t('inviteCollaboratorSubmit')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          {inviteError ? <ErrorNotice title={inviteError} /> : null}
          <TextInput
            label={t('inviteCollaboratorHandleLabel')}
            placeholder={t('inviteCollaboratorHandlePlaceholder')}
            value={identifier}
            onChange={(event) => setIdentifier(event.target.value)}
            disabled={inviting}
            autoFocus
            onKeyDown={(event) => {
              if (event.key === 'Enter' && identifier.trim() && !inviting) void invite();
            }}
          />
        </div>
      </Dialog>
    </section>
  );
}
