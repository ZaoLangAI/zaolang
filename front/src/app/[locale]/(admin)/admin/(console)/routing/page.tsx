import { getTranslations } from 'next-intl/server';

import { AgentCatalogProvider } from '@/components/admin/workflows/agent-catalog';
import { WorkflowEditor } from '@/components/admin/workflows/workflow-editor';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { AgentNode, AgentProfile, NodeTypeView, Page, RolePreset } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminRouting');
  return { title: t('title') };
}

export default async function AdminRoutingPage() {
  const t = await getTranslations('adminRouting');
  // All four are small, shared by every node picker on the canvas, and
  // unchanged for the life of a page view — fetching them once here is what
  // keeps clicking around a graph from burning through `admin_read`.
  const [nodeTypes, agentNodes, agentProfiles, rolePresets] = await Promise.all([
    adminFetch<Page<NodeTypeView>>('/v1/admin/workflow-templates/node-types'),
    adminFetch<Page<AgentNode>>('/v1/admin/agent-nodes'),
    adminFetch<Page<AgentProfile>>('/v1/admin/agent-profiles'),
    adminFetch<Page<RolePreset>>('/v1/admin/agent-node-presets'),
  ]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <AgentCatalogProvider
        seed={{
          nodes: agentNodes.items,
          profiles: agentProfiles.items,
          presets: rolePresets.items,
        }}
      >
        <WorkflowEditor nodeTypeCatalog={nodeTypes.items} />
      </AgentCatalogProvider>
    </div>
  );
}
