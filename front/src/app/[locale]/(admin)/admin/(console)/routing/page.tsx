import { getTranslations } from 'next-intl/server';

import { WorkflowEditor } from '@/components/admin/workflows/workflow-editor';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetch } from '@/lib/api/admin-server';
import type { NodeTypeView, Page } from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminRouting');
  return { title: t('title') };
}

export default async function AdminRoutingPage() {
  const t = await getTranslations('adminRouting');
  const nodeTypes = await adminFetch<Page<NodeTypeView>>('/v1/admin/workflow-templates/node-types');

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />
      <WorkflowEditor nodeTypeCatalog={nodeTypes.items} />
    </div>
  );
}
