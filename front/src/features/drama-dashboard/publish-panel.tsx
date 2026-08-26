'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { TextArea, TextInput } from '@/components/ui/field';
import { Badge } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { isApiError } from '@/lib/api/errors';

import * as distributionApi from './distribution-api';

const CHANNEL_LABEL_KEYS: Record<string, string> = {
  manual_download: 'channelManualDownload',
  douyin: 'channelDouyin',
  kuaishou: 'channelKuaishou',
};

const RESULT_TONE: Record<string, 'success' | 'danger' | 'neutral'> = {
  submitted: 'success',
  exported: 'neutral',
  ready: 'neutral',
  failed: 'danger',
};

/**
 * One-click publish for an episode's canonical work. Manual download is
 * always available (today's existing behaviour); Douyin/Kuaishou only show
 * up once the org's own app credentials are configured — see
 * `PlatformConnect`'s "not configured" hint, which applies here too.
 */
export function PublishPanel({ workId }: { workId: string }) {
  const t = useTranslations('editor');
  const { notify } = useToast();

  const [configStatus, setConfigStatus] = useState<distributionApi.ConfigStatus | null>(null);
  const [accounts, setAccounts] = useState<distributionApi.PlatformAccountLink[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set(['manual_download']));
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [hashtagsInput, setHashtagsInput] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [results, setResults] = useState<distributionApi.PublicationFanoutItem[]>([]);

  useEffect(() => {
    void Promise.all([distributionApi.getConfigStatus(), distributionApi.listPlatformAccounts()])
      .then(([status, linked]) => {
        setConfigStatus(status);
        setAccounts(linked);
      })
      .catch(() => undefined);
  }, []);

  const linkedChannels = new Set(accounts.map((account) => account.channel));
  const availableChannels = ['manual_download', 'douyin', 'kuaishou'].filter(
    (channel) =>
      channel === 'manual_download' ||
      ((configStatus?.[channel as 'douyin' | 'kuaishou'] ?? false) && linkedChannels.has(channel)),
  );

  const toggle = (channel: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(channel)) next.delete(channel);
      else next.add(channel);
      return next;
    });
  };

  const trimmedTitle = title.trim();

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!trimmedTitle || selected.size === 0) return;
    setPublishing(true);
    setResults([]);
    const hashtags = hashtagsInput
      .split(/[,\s]+/)
      .map((tag) => tag.replace(/^#/, '').trim())
      .filter(Boolean);
    void distributionApi
      .publishFanout(workId, {
        channels: [...selected],
        title: trimmedTitle,
        description: description.trim() || undefined,
        hashtags,
      })
      .then((result) => {
        setResults(result.results);
        notify(t('publishSucceeded'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setPublishing(false));
  };

  return (
    <div className="flex flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
      <div>
        <h3 className="text-sm font-semibold">{t('publishPanelTitle')}</h3>
        <p className="mt-1 text-xs text-muted">{t('publishPanelHint')}</p>
      </div>

      <form className="flex flex-col gap-3" onSubmit={submit}>
        <div className="flex flex-wrap gap-3">
          {availableChannels.map((channel) => (
            <label key={channel} className="flex cursor-pointer items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={selected.has(channel)}
                onChange={() => toggle(channel)}
                disabled={publishing}
                className="size-4 accent-[var(--primary)]"
              />
              {t(CHANNEL_LABEL_KEYS[channel] ?? channel)}
            </label>
          ))}
        </div>

        <TextInput
          label={t('publishTitleLabel')}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          disabled={publishing}
          required
        />
        <TextArea
          label={t('publishDescriptionLabel')}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          disabled={publishing}
        />
        <TextInput
          label={t('publishHashtagsLabel')}
          value={hashtagsInput}
          onChange={(event) => setHashtagsInput(event.target.value)}
          disabled={publishing}
          placeholder="#短剧 #精彩"
        />

        <div>
          <Button
            type="submit"
            loading={publishing}
            disabled={!trimmedTitle || selected.size === 0}
          >
            {t('publishSubmit', { count: selected.size })}
          </Button>
        </div>
      </form>

      {results.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {results.map((result) => (
            <li key={result.channel} className="flex items-center gap-2 text-xs">
              <Badge tone={RESULT_TONE[result.status] ?? 'neutral'}>
                {t(CHANNEL_LABEL_KEYS[result.channel] ?? result.channel)}
              </Badge>
              <span className="text-muted">
                {result.error
                  ? result.error
                  : result.reason === 'manual_download'
                    ? t('publishManualFallback')
                    : result.reason === 'not_configured'
                      ? t('platformNotConfiguredHint')
                      : result.reason === 'not_linked'
                        ? t('publishNotLinked')
                        : t(`publishStatus${result.status.charAt(0).toUpperCase()}${result.status.slice(1)}`)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
