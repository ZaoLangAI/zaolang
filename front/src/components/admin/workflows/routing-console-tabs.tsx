'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { WorkflowEditor } from '@/components/admin/workflows/workflow-editor';
import type { NodeTypeView } from '@/lib/api/admin-types';

const TABS = ['workflow', 'providers'] as const;
type Tab = (typeof TABS)[number];

/**
 * `/admin/routing`'s two halves: the configurable node-graph editor (new)
 * and the existing provider stats + routing-weights editor (unchanged,
 * `providersPanel` is rendered exactly as the page built it before).
 */
export function RoutingConsoleTabs({
  nodeTypeCatalog,
  providersPanel,
}: {
  nodeTypeCatalog: NodeTypeView[];
  providersPanel: React.ReactNode;
}) {
  const t = useTranslations('adminRouting');
  const [tab, setTab] = useState<Tab>('workflow');

  const labels: Record<Tab, string> = {
    workflow: t('tabWorkflow'),
    providers: t('tabProviders'),
  };

  return (
    <div>
      <div role="tablist" aria-label={t('title')} className="flex gap-6 border-b border-border">
        {TABS.map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={
              tab === id
                ? '-mb-px border-b-2 border-primary pb-3 text-sm text-text'
                : '-mb-px border-b-2 border-transparent pb-3 text-sm text-muted hover:text-text'
            }
          >
            {labels[id]}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === 'workflow' ? (
          <WorkflowEditor nodeTypeCatalog={nodeTypeCatalog} />
        ) : (
          providersPanel
        )}
      </div>
    </div>
  );
}
