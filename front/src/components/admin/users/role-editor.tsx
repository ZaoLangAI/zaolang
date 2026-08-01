'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { DangerConfirm } from '@/components/admin/danger-confirm';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/field';
import { useToast } from '@/components/ui/toast';
import { adminApi } from '@/lib/api/admin-client';

const ALL_ROLES = ['user', 'reviewer', 'operator', 'admin'] as const;

type Props = {
  userId: string;
  roles: string[];
  onSaved: () => void;
};

export function RoleEditor({ userId, roles, onSaved }: Props) {
  const t = useTranslations('adminUsers');
  const tAdmin = useTranslations('admin');
  const { notify } = useToast();

  const [selected, setSelected] = useState<string[]>(roles);
  const [confirming, setConfirming] = useState(false);

  const dirty = selected.length !== roles.length || selected.some((role) => !roles.includes(role));

  const save = async (reason: string) => {
    await adminApi.post(`/v1/admin/users/${userId}/roles`, {
      roles: selected,
      reason,
      confirm: true,
    });
    notify(t('grantRoles'), 'success');
    onSaved();
  };

  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">{t('grantRoles')}</h3>
      <ul className="flex flex-col gap-2">
        {ALL_ROLES.map((role) => (
          <li key={role}>
            <Switch
              label={role}
              checked={selected.includes(role)}
              onChange={(checked) =>
                setSelected((current) =>
                  checked ? [...current, role] : current.filter((item) => item !== role),
                )
              }
            />
          </li>
        ))}
      </ul>
      <Button
        size="sm"
        variant="secondary"
        className="mt-3"
        disabled={!dirty}
        onClick={() => setConfirming(true)}
      >
        {tAdmin('save')}
      </Button>

      <DangerConfirm
        open={confirming}
        onClose={() => setConfirming(false)}
        title={t('grantRoles')}
        description={t('rolesHint')}
        reasonLabel={tAdmin('dangerReason')}
        onConfirm={save}
      />
    </section>
  );
}
