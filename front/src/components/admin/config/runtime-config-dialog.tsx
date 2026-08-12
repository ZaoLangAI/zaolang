'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import {
  RuntimeConfigPanel,
  type RuntimeConfigKind,
} from '@/components/admin/config/runtime-config-panel';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import type { ConfigValue } from '@/lib/api/admin-types';

export interface RuntimeConfigDialogItem {
  initial: ConfigValue;
  kind: RuntimeConfigKind;
  title: string;
}

/** Keeps domain-owned runtime settings available without turning the business
 * page itself into a configuration dashboard. */
export function RuntimeConfigDialog({
  title,
  items,
}: {
  title: string;
  items: RuntimeConfigDialogItem[];
}) {
  const t = useTranslations('adminConfig');
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
        {t('configure')}
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        size="xl"
        title={title}
        description={t('businessDialogHint')}
      >
        <div className="flex max-h-[72vh] flex-col gap-5 overflow-y-auto pr-1">
          {items.map((item) => (
            <RuntimeConfigPanel
              key={item.initial.key}
              initial={item.initial}
              kind={item.kind}
              title={item.title}
            />
          ))}
        </div>
      </Dialog>
    </>
  );
}
