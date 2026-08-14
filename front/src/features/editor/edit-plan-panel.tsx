'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { TextArea } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';

import * as editorApi from './api';
import type { EditCommand } from './engine/ports';

export function EditPlanPanel({
  cutId,
  leaseId,
  leaseToken,
  disabled,
  onApplied,
}: {
  cutId: string;
  leaseId: string | null;
  leaseToken: string | null;
  disabled: boolean;
  onApplied: () => void;
}) {
  const t = useTranslations('editor');
  const { notify } = useToast();
  const [goal, setGoal] = useState('');
  const [plan, setPlan] = useState<editorApi.EditPlan | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  const generate = async () => {
    setBusy(true);
    try {
      const next = await editorApi.createEditPlan(cutId, goal);
      setPlan(next);
      setSelected(new Set(next.commands.map((_, index) => index)));
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!plan || !leaseId || !leaseToken) return;
    setBusy(true);
    try {
      await editorApi.applyEditPlan(plan.id, leaseId, leaseToken, [...selected]);
      onApplied();
      notify(t('saveRevision'), 'success');
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      await editorApi.rejectEditPlan(plan.id);
      setPlan(null);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold">{t('planTitle')}</h2>
      <TextArea
        label={t('planGoal')}
        value={goal}
        onChange={(event) => setGoal(event.target.value)}
        rows={3}
        disabled={disabled || busy}
      />
      <Button onClick={() => void generate()} loading={busy} disabled={disabled || !goal.trim()}>
        {t('planGenerate')}
      </Button>
      {plan ? (
        plan.commands.length === 0 ? (
          <p className="text-xs text-muted">{t('planEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {plan.commands.map((command, index) => (
              <li key={`${command.type}-${index}`}>
                <label className="flex items-start gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={selected.has(index)}
                    onChange={() => {
                      const next = new Set(selected);
                      if (next.has(index)) next.delete(index);
                      else next.add(index);
                      setSelected(next);
                    }}
                  />
                  <span>
                    {command.type}
                    {commandHint(command)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )
      ) : null}
      {plan ? (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={() => void apply()}
            disabled={disabled || busy || !leaseToken || selected.size === 0}
          >
            {t('planApply')}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => void reject()} disabled={busy}>
            {t('planReject')}
          </Button>
        </div>
      ) : null}
      {plan?.warnings?.length ? (
        <ErrorNotice title={t('planTitle')} detail={plan.warnings.map(String).join(' · ')} />
      ) : null}
    </section>
  );
}

function commandHint(command: EditCommand): string {
  if ('text' in command && command.text) return ` · ${command.text}`;
  if ('element_id' in command && command.element_id) return ` · ${command.element_id}`;
  return '';
}
