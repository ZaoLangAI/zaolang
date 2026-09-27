'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/toast';
import * as distributionApi from '@/features/drama-dashboard/distribution-api';
import { isApiError } from '@/lib/api/errors';

const CHANNELS = ['douyin', 'kuaishou'] as const;

const CHANNEL_LABEL_KEYS: Record<(typeof CHANNELS)[number], string> = {
  douyin: 'connectDouyin',
  kuaishou: 'connectKuaishou',
};

/**
 * "连接抖音/快手账号" — per-user, not per-series/episode, so it lives on
 * the account settings page (`/profile/settings?section=platforms`) rather
 * than the drama dashboard.
 *
 * Neither platform's real AppKey/AppSecret exists yet (the org hasn't
 * finished platform registration), so `config-status` reports both as
 * unconfigured today — the buttons render disabled with a hint rather than
 * a dead click, and this component works unchanged the day real credentials
 * land.
 */
export function PlatformConnect() {
  const t = useTranslations('editor');
  const { notify } = useToast();

  const [configStatus, setConfigStatus] = useState<distributionApi.ConfigStatus | null>(null);
  const [accounts, setAccounts] = useState<distributionApi.PlatformAccountLink[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([distributionApi.getConfigStatus(), distributionApi.listPlatformAccounts()])
      .then(([status, linked]) => {
        setConfigStatus(status);
        setAccounts(linked);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const connect = (channel: string) => {
    setConnecting(channel);
    void distributionApi
      .getAuthorizeUrl(channel)
      .then(({ authorize_url }) => {
        window.location.href = authorize_url;
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
        setConnecting(null);
      });
  };

  const disconnect = (linkId: string) => {
    setDisconnecting(linkId);
    void distributionApi
      .disconnectPlatformAccount(linkId)
      .then(() => {
        setAccounts((current) => current.filter((item) => item.id !== linkId));
        notify(t('platformDisconnected'), 'success');
      })
      .catch((error: unknown) => {
        notify(isApiError(error) ? error.message : t('commandFailed'), 'error');
      })
      .finally(() => setDisconnecting(null));
  };

  if (!loaded) return null;

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold">{t('platformConnectTitle')}</h2>
      <p className="mt-1 text-xs text-muted">{t('platformConnectHint')}</p>

      <div className="mt-4 flex flex-wrap gap-3">
        {CHANNELS.map((channel) => {
          const isConfigured = configStatus?.[channel] ?? false;
          return (
            <Button
              key={channel}
              size="sm"
              variant="secondary"
              disabled={!isConfigured}
              loading={connecting === channel}
              onClick={() => connect(channel)}
              title={isConfigured ? undefined : t('platformNotConfiguredHint')}
            >
              {t(CHANNEL_LABEL_KEYS[channel])}
            </Button>
          );
        })}
      </div>
      {CHANNELS.some((channel) => !(configStatus?.[channel] ?? false)) ? (
        <p className="mt-2 text-xs text-muted">{t('platformNotConfiguredHint')}</p>
      ) : null}

      {accounts.length > 0 ? (
        <ul className="mt-4 flex flex-col gap-2">
          {accounts.map((account) => (
            <li
              key={account.id}
              className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-xs"
            >
              <span>
                {t(`channel${account.channel.charAt(0).toUpperCase()}${account.channel.slice(1)}`)}
                {' · '}
                {t('connectedAs', {
                  account: account.external_account_label ?? account.external_account_id,
                })}
              </span>
              <Button
                size="sm"
                variant="secondary"
                loading={disconnecting === account.id}
                onClick={() => disconnect(account.id)}
              >
                {t('platformDisconnect')}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
