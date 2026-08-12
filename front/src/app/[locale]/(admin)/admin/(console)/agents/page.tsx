import { getTranslations } from 'next-intl/server';

import { AgentSkillsPanel } from '@/components/admin/agents/agent-skills-panel';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { AgentNode, Page } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminAgents');
  return { title: t('title') };
}

export default async function AdminAgentsPage() {
  const t = await getTranslations('adminAgents');

  const nodes = await adminFetch<Page<AgentNode>>('/v1/admin/agent-nodes');

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />

      <AgentSkillsPanel initial={nodes.items} />
    </div>
  );
}
