'use client';

import { useTranslations } from 'next-intl';

import type { ScriptLintIssue } from './api';

/**
 * The deterministic script lint (`GET /v1/scripts/{id}` → `lint`): writing
 * rules the script coach already asks for, checked in code on the saved
 * script. Collapsed by default and purely advisory — nothing here blocks a
 * turn or a generation. Each finding names where it is and, when a `format`
 * skill fixes that axis, which one to `@` into the next revision.
 */
export function ScriptLintPanel({ issues }: { issues: ScriptLintIssue[] }) {
  const t = useTranslations('scriptStudio');
  if (issues.length === 0) return null;
  const warnings = issues.filter((issue) => issue.severity === 'warning').length;

  return (
    <details className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-xs">
      <summary className="cursor-pointer select-none font-medium">
        {t('lintTitle', { count: issues.length, warnings })}
      </summary>
      <p className="mt-1 text-muted">{t('lintHint')}</p>
      <ul className="mt-2 flex flex-col gap-2">
        {issues.map((issue, index) => (
          <li
            key={`${issue.code}:${issue.scene_index ?? 'episode'}:${issue.block_index ?? 'segment'}:${index}`}
            className="flex flex-col gap-0.5"
          >
            <span className="text-muted">
              {issue.heading || t('lintEpisode')}
              {issue.block_index !== null ? ` · ${t('lintBlock', { index: issue.block_index + 1 })}` : ''}
            </span>
            <span className={issue.severity === 'warning' ? 'text-amber' : undefined}>
              {issue.message}
            </span>
            {issue.suggested_skills.length > 0 ? (
              <span className="text-muted">
                {t('lintSkills', { skills: issue.suggested_skills.join('、') })}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  );
}
