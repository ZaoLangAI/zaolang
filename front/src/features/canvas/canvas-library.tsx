'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Button } from '@/components/ui/button';
import { Card, EmptyState, ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { useRouter } from '@/i18n/navigation';

import { createCanvasProject, listCanvasProjects, type CanvasProjectSummary } from './api';

/** The free-sandbox entry point: every canvas the viewer can open, and the
 * button that creates a new unbound one. Drama canvases are also listed here
 * so a user has one place that answers "what am I working on", but their
 * primary entry stays the series page. */
export function CanvasLibrary() {
  const t = useTranslations('canvas');
  const router = useRouter();
  const { status } = useSession();
  const [projects, setProjects] = useState<CanvasProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    // Wait for the session: firing this while anonymous just produces a
    // "please sign in" error where a sign-in prompt belongs.
    if (status !== 'authenticated') return undefined;
    let cancelled = false;
    listCanvasProjects()
      .then((rows) => {
        if (!cancelled) setProjects(rows);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [status]);

  const create = useCallback(async () => {
    setCreating(true);
    try {
      const created = await createCanvasProject({ title: t('newCanvasDefaultTitle') });
      router.push(`/canvas/${created.id}`);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setCreating(false);
    }
  }, [router, t]);

  if (status === 'anonymous') return <SignInPrompt description={t('signInHint')} />;
  if (error) return <ErrorNotice title={t('loadFailed')} detail={error} />;
  if (!projects) return <Skeleton className="h-40 w-full" />;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={create} disabled={creating}>
          {t('newCanvas')}
        </Button>
      </div>
      {projects.length === 0 ? (
        <EmptyState title={t('emptyTitle')} description={t('emptyHint')} />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <li key={project.id}>
              <Card className="h-full">
                <button
                  type="button"
                  onClick={() => router.push(`/canvas/${project.id}`)}
                  className="w-full space-y-1 text-left"
                >
                  <p className="truncate text-sm font-medium text-text">{project.title}</p>
                  <p className="text-xs text-muted">
                    {t(`mode.${project.mode}`)} · {t('nodeCount', { count: project.node_count })}
                  </p>
                </button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
