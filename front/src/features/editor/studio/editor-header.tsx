'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { ThemeMenu } from '@/components/layout/theme-menu';
import { Button, IconButton } from '@/components/ui/button';
import { IconClose, IconDownload, IconQuestion } from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { useRouter } from '@/i18n/navigation';

/** Below this many seconds left, the countdown turns into a warning colour —
 * a healthy lease renews itself every 30s heartbeat well before its 5-minute
 * TTL runs out, so anything under a minute signals the heartbeat has
 * actually stalled (dropped tab focus, network hiccup) rather than normal
 * operation. */
const WARNING_THRESHOLD_SECONDS = 60;

function useSecondsUntil(isoTime: string | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isoTime) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [isoTime]);
  if (!isoTime) return null;
  return Math.max(0, Math.round((new Date(isoTime).getTime() - now) / 1000));
}

function LeaseCountdown({ expiresAt }: { expiresAt: string | null }) {
  const t = useTranslations('editor');
  const seconds = useSecondsUntil(expiresAt);
  if (seconds === null) return null;
  const minutes = Math.floor(seconds / 60);
  const remSeconds = seconds % 60;
  const label = `${minutes}:${String(remSeconds).padStart(2, '0')}`;
  return (
    <span
      role="status"
      aria-live="off"
      title={t('leaseCountdownHint')}
      className={cn(
        'shrink-0 rounded-full border px-2 py-0.5 font-mono text-[11px]',
        seconds <= WARNING_THRESHOLD_SECONDS
          ? 'border-danger/40 text-danger'
          : 'border-border text-muted',
      )}
    >
      {t('leaseCountdownLabel', { time: label })}
    </span>
  );
}

/** Click-to-edit title, mirroring OpenCut's `ProjectNameEditor` (Enter commits, Escape reverts, blur commits). */
function InlineTitle({
  title,
  disabled,
  onRename,
}: {
  title: string;
  disabled: boolean;
  onRename: (name: string) => void;
}) {
  const t = useTranslations('editor');
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (next && next !== title) onRename(next);
    else setDraft(title);
  };

  if (!editing) {
    return (
      <button
        type="button"
        disabled={disabled}
        title={disabled ? undefined : t('renameCutHint')}
        onClick={() => {
          setDraft(title);
          setEditing(true);
        }}
        className={cn(
          'min-w-0 truncate rounded px-1 text-sm font-semibold text-text',
          disabled ? 'cursor-default' : 'hover:bg-surface-soft',
        )}
      >
        {title}
      </button>
    );
  }
  return (
    <input
      autoFocus
      value={draft}
      maxLength={120}
      aria-label={t('renameCutHint')}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === 'Enter') commit();
        else if (event.key === 'Escape') {
          setDraft(title);
          setEditing(false);
        }
      }}
      className="min-w-0 rounded border border-border bg-surface px-1 text-sm font-semibold text-text outline-none focus:border-primary"
    />
  );
}

/**
 * Adapted from OpenCut's `components/editor/editor-header.tsx` — a slim
 * top bar carrying the project name (click to rename), an export button and
 * the theme toggle (this route has no `TopBar`, so it would otherwise be
 * unreachable). OpenCut's Discord link, feedback popover and delete-project
 * dialog are dropped; export jumps to the pinned panel in the properties
 * column rather than opening a dialog.
 */
export function EditorHeader({
  title,
  episodeId,
  saveStatus,
  leaseExpiresAt,
  disabled,
  onRename,
  onExport,
  onShowShortcuts,
}: {
  title: string;
  episodeId: string | null;
  saveStatus: 'idle' | 'saving' | 'saved';
  /** Own write-lease expiry, or `null` while read-only / not yet acquired. */
  leaseExpiresAt: string | null;
  disabled: boolean;
  onRename: (name: string) => void;
  onExport: () => void;
  onShowShortcuts: () => void;
}) {
  const t = useTranslations('editor');
  const router = useRouter();

  const closeStudio = () => {
    window.close();
    router.push(episodeId ? `/create/short/episodes/${episodeId}` : '/create/short');
  };

  return (
    <header className="flex h-[3.4rem] shrink-0 items-center justify-between border-b border-border px-3">
      <div className="flex min-w-0 items-center gap-2">
        <IconButton label={t('closeStudio')} onClick={closeStudio}>
          <IconClose className="size-4" />
        </IconButton>
        <InlineTitle title={title} disabled={disabled} onRename={onRename} />
        {saveStatus !== 'idle' ? (
          <span
            role="status"
            aria-live="polite"
            className="shrink-0 text-xs text-muted transition-opacity"
          >
            {saveStatus === 'saving' ? t('savingInProgress') : t('saveRevision')}
          </span>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <LeaseCountdown expiresAt={leaseExpiresAt} />
        <IconButton label={t('shortcutsTitle')} onClick={onShowShortcuts}>
          <IconQuestion className="size-4" />
        </IconButton>
        <Button size="sm" onClick={onExport}>
          <IconDownload className="size-4" />
          {t('exportButton')}
        </Button>
        <ThemeMenu />
      </div>
    </header>
  );
}
