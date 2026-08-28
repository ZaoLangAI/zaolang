'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { IconArrowRight, IconCheck, IconCopy } from '@/components/ui/icons';
import { Badge } from '@/components/ui/primitives';
import { useRouter } from '@/i18n/navigation';
import type { GenerationJob, VideoAnalysisShot } from '@/lib/api/types';

/**
 * The structured `video_analysis` result — shared by the studio's own
 * just-submitted panel and the history detail view, so there is exactly one
 * place that renders `job.analysis` (see `zaolang-generation-jobs`'s
 * `analysis_result_json` echo).
 *
 * Renders nothing for a job whose analysis is not (yet) populated; callers
 * are responsible for the in-progress/failed states around it.
 */
export function VideoAnalysisResult({
  job,
  videoUrl,
}: {
  job: GenerationJob;
  videoUrl?: string | null;
}) {
  const t = useTranslations('videoAnalysisPage');
  const tActions = useTranslations('actions');
  const router = useRouter();
  const [copied, setCopied] = useState(false);

  const analysis = job.analysis;
  if (!analysis) return null;
  const styleTags = analysis.style_tags ?? [];
  const shots = analysis.shots ?? [];

  const copyPrompt = () => {
    void navigator.clipboard.writeText(analysis.composed_prompt);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  const useForVideoCreation = () =>
    router.push(`/create/new?mode=video_creation&prompt=${encodeURIComponent(analysis.composed_prompt)}`);
  const useForScriptWriting = () =>
    router.push(`/create/script?ideaPrefill=${encodeURIComponent(analysis.composed_prompt)}`);

  return (
    <div className="flex flex-col gap-5">
      {videoUrl ? (
        <video
          src={videoUrl}
          controls
          preload="metadata"
          className="w-full rounded-[var(--radius-md)] border border-border bg-surface-soft"
        />
      ) : null}

      {analysis.summary ? (
        <div className="flex flex-col gap-1.5">
          <h3 className="text-sm font-semibold">{t('resultSummary')}</h3>
          <p className="text-sm leading-relaxed text-muted">{analysis.summary}</p>
        </div>
      ) : null}

      {analysis.composed_prompt ? (
        <div className="rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">{t('resultComposedPrompt')}</h3>
            <Button
              size="sm"
              variant="secondary"
              onClick={copyPrompt}
              icon={copied ? <IconCheck className="size-4" /> : <IconCopy className="size-4" />}
            >
              {copied ? tActions('copied') : tActions('copy')}
            </Button>
          </div>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">
            {analysis.composed_prompt}
          </p>
        </div>
      ) : null}

      {styleTags.length > 0 || analysis.pacing ? (
        <div className="flex flex-wrap items-center gap-2">
          {styleTags.map((tag) => (
            <Badge key={tag}>{tag}</Badge>
          ))}
          {analysis.pacing ? <Badge tone="amber">{t('resultPacing', { pacing: analysis.pacing })}</Badge> : null}
        </div>
      ) : null}

      {shots.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">{t('resultShots')}</h3>
          <ul className="flex flex-col gap-2">
            {shots.map((shot, index) => (
              <ShotCard key={`${shot.time_range}-${index}`} shot={shot} />
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-3 border-t border-border pt-4">
        <Button onClick={useForVideoCreation} icon={<IconArrowRight className="size-4" />}>
          {t('useForVideoCreation')}
        </Button>
        <Button
          variant="secondary"
          onClick={useForScriptWriting}
          icon={<IconArrowRight className="size-4" />}
        >
          {t('useForScriptWriting')}
        </Button>
      </div>
    </div>
  );
}

function ShotCard({ shot }: { shot: VideoAnalysisShot }) {
  const t = useTranslations('videoAnalysisPage');
  const fields: Array<[string, string]> = [
    [t('shotCameraMovement'), shot.camera_movement],
    [t('shotScene'), shot.scene],
    [t('shotSubjectAction'), shot.subject_action],
    [t('shotLightingMood'), shot.lighting_mood],
    [t('shotTransitionIn'), shot.transition_in],
  ].filter(([, value]) => Boolean(value)) as Array<[string, string]>;

  return (
    <li className="rounded-[var(--radius-sm)] border border-border p-3 text-xs">
      {shot.time_range ? <p className="tabular font-medium text-muted">{shot.time_range}</p> : null}
      <dl className="mt-1.5 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt className="text-muted">{label}</dt>
            <dd className="mt-0.5">{value}</dd>
          </div>
        ))}
      </dl>
    </li>
  );
}
