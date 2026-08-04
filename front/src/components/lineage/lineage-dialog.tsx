'use client';

import { useTranslations } from 'next-intl';

import { LineageExplorer } from '@/components/lineage/lineage-explorer';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { useRouter } from '@/i18n/navigation';

export function LineageDialog({
  workId,
  open,
  onClose,
}: {
  workId: string;
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslations('lineagePanel');
  const tActions = useTranslations('actions');
  const router = useRouter();

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('title')}
      size="xl"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {tActions('close')}
        </Button>
      }
    >
      <LineageExplorer
        workId={workId}
        onOpenWork={(id) => {
          onClose();
          router.push(`/work/${id}`);
        }}
      />
    </Dialog>
  );
}
