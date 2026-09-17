'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { AppealsConsole } from '@/components/admin/appeals/appeals-console';
import { DuplicateGroups } from '@/components/admin/moderation/duplicate-groups';
import { ModerationQueue } from '@/components/admin/moderation/moderation-queue';
import { ReportsConsole } from '@/components/admin/reports/reports-console';
import { cn } from '@/lib/cn';

const TABS = ['queue', 'reports', 'appeals'] as const;
export type ModerationTab = (typeof TABS)[number];

/**
 * Reports and appeals both act on the same works the moderation queue does
 * (subject preview, hide/tombstone/restore) and share the queue's
 * `open_report_count` signal, so they live as tabs on one shell rather than
 * three separate consoles.
 */
export function ModerationWorkspace({
  initialTab,
  configAction,
}: {
  initialTab: ModerationTab;
  configAction: React.ReactNode;
}) {
  const tQueue = useTranslations('adminModeration');
  const tReports = useTranslations('adminReports');
  const tAppeals = useTranslations('adminAppeals');
  const [tab, setTab] = useState<ModerationTab>(initialTab);

  const labels: Record<ModerationTab, string> = {
    queue: tQueue('title'),
    reports: tReports('title'),
    appeals: tAppeals('title'),
  };

  return (
    <div className="flex flex-col gap-6">
      <div
        role="tablist"
        aria-label={tQueue('title')}
        className="flex flex-wrap gap-6 border-b border-border"
      >
        {TABS.map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              '-mb-px border-b-2 pb-3 text-sm transition-colors',
              tab === id
                ? 'border-primary text-text'
                : 'border-transparent text-muted hover:text-text',
            )}
          >
            {labels[id]}
          </button>
        ))}
      </div>

      {tab === 'queue' ? (
        <>
          <ModerationQueue configAction={configAction} />
          <DuplicateGroups />
        </>
      ) : null}
      {tab === 'reports' ? <ReportsConsole /> : null}
      {tab === 'appeals' ? <AppealsConsole /> : null}
    </div>
  );
}
