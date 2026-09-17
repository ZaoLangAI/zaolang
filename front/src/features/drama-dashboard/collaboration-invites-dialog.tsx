'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { Avatar } from '@/components/work/avatar';
import * as editorApi from '@/features/editor/api';
import { isApiError } from '@/lib/api/errors';

/**
 * Every pending "邀请你共创" invite the signed-in user has received.
 * Accepting turns the series into a shared card on the dashboard; declining
 * removes it from this list without notifying the inviter further.
 */
export function CollaborationInvitesDialog({
  invites,
  open,
  onClose,
  onResolved,
}: {
  invites: editorApi.CollaborationInvite[];
  open: boolean;
  onClose: () => void;
  onResolved: (invite: editorApi.CollaborationInvite) => void;
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);

  const respond = (invite: editorApi.CollaborationInvite, accept: boolean) => {
    setBusyId(invite.id);
    const action = accept
      ? editorApi.acceptCollaborationInvite(invite.id)
      : editorApi.declineCollaborationInvite(invite.id);
    void action
      .then(() => {
        notify(
          accept ? t('collaborationInviteAcceptedDone') : t('collaborationInviteDeclinedDone'),
          'success',
        );
        onResolved(invite);
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setBusyId(null));
  };

  return (
    <Dialog open={open} onClose={onClose} title={t('collaborationInvitesDialogTitle')} size="sm">
      {invites.length === 0 ? (
        <EmptyState title={t('collaborationInvitesEmpty')} />
      ) : (
        <ul className="flex flex-col gap-3">
          {invites.map((invite) => (
            <li
              key={invite.id}
              className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3"
            >
              <div className="flex items-center gap-3">
                <Avatar src={invite.inviter.avatar_url} name={invite.inviter.display_name} size="sm" />
                <p className="min-w-0 flex-1 text-sm">
                  {t('collaborationInvitedBy', {
                    name: invite.inviter.display_name,
                    series: invite.series_title,
                  })}
                </p>
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busyId === invite.id}
                  onClick={() => respond(invite, false)}
                >
                  {t('collaborationInviteDecline')}
                </Button>
                <Button size="sm" loading={busyId === invite.id} onClick={() => respond(invite, true)}>
                  {t('collaborationInviteAccept')}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
