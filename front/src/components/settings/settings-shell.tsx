'use client';

import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { useTheme } from '@/components/theme/theme-provider';
import { Avatar } from '@/components/work/avatar';
import { OptionGroup } from '@/components/studio/option-group';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Switch, TextArea, TextInput } from '@/components/ui/field';
import {
  IconBell,
  IconEye,
  IconGear,
  IconLock,
  IconMonitor,
  IconMoon,
  IconSun,
} from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { usePathname, useRouter } from '@/i18n/navigation';
import { regionLocale, regions, type Region } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { Me, ThemePreference } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { uploadFile } from '@/lib/upload';

const SECTIONS = ['profile', 'privacy', 'notifications', 'display'] as const;
type Section = (typeof SECTIONS)[number];

/**
 * Account settings.
 *
 * Every control writes through immediately rather than into a form that needs
 * a save button: the same preferences are changeable from the top bar, and two
 * places editing one value with different commit rules is how they drift apart.
 */
export function SettingsShell({ me }: { me: Me }) {
  const t = useTranslations('settingsPage');
  const tTheme = useTranslations('theme');
  const tRegion = useTranslations('region');
  const tActions = useTranslations('actions');
  const { notify } = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { refresh } = useSession();
  const { preference, setPreference, reduceMotion, setReduceMotion } = useTheme();

  const [section, setSection] = useState<Section>('profile');
  const [displayName, setDisplayName] = useState(me.profile?.display_name ?? '');
  const [bio, setBio] = useState(me.profile?.bio ?? '');
  const [location, setLocation] = useState(me.profile?.location ?? '');
  const [publicProfile, setPublicProfile] = useState(me.profile?.public_profile ?? true);
  const [notifyOnRemix, setNotifyOnRemix] = useState(me.profile?.notify_on_remix ?? true);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const avatarInput = useRef<HTMLInputElement>(null);

  const icons: Record<Section, React.ReactNode> = {
    profile: <IconGear className="size-4" />,
    privacy: <IconLock className="size-4" />,
    notifications: <IconBell className="size-4" />,
    display: <IconEye className="size-4" />,
  };
  const labels: Record<Section, string> = {
    profile: t('navProfile'),
    privacy: t('navPrivacy'),
    notifications: t('navNotifications'),
    display: t('navDisplay'),
  };

  const saveProfile = async (patch: Record<string, unknown>) => {
    setSaving(true);
    setError(null);
    try {
      await api.patch('/v1/auth/me/profile', patch);
      notify(t('saved'), 'success');
    } catch {
      setError(t('saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const savePreferences = async (patch: Record<string, unknown>) => {
    try {
      await api.patch('/v1/auth/me/preferences', patch);
      await refresh();
    } catch {
      setError(t('saveFailed'));
    }
  };

  const changeAvatar = async (file: File | undefined) => {
    if (!file) return;
    try {
      const asset = await uploadFile(file, 'avatar');
      setAvatarUrl(asset.url ?? null);
      await saveProfile({ avatar_asset_id: asset.id });
    } catch {
      setError(t('saveFailed'));
    }
  };

  const requestData = async (type: 'export' | 'delete', reason?: string) => {
    try {
      await api.post('/v1/me/data-requests', { type, reason });
      notify(type === 'export' ? t('exportRequested') : t('deleteRequested'), 'success');
      setConfirmDelete(false);
    } catch {
      setError(t('saveFailed'));
    }
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav
        aria-label={t('title')}
        className="h-fit rounded-[var(--radius-md)] border border-border bg-surface p-2"
      >
        <ul className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
          {SECTIONS.map((id) => (
            <li key={id} className="shrink-0 lg:w-full">
              <button
                type="button"
                aria-current={section === id ? 'true' : undefined}
                onClick={() => setSection(id)}
                className={cn(
                  'flex w-full items-center gap-2.5 rounded-[var(--radius-sm)] px-3 py-2.5 text-sm transition-colors',
                  section === id
                    ? 'bg-primary/12 text-primary'
                    : 'text-muted hover:bg-surface-soft hover:text-text',
                )}
              >
                {icons[id]}
                {labels[id]}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex flex-col gap-5">
        {error ? <ErrorNotice title={error} /> : null}

        {section === 'profile' ? (
          <Panel title={t('profileSection')}>
            <div className="flex items-center gap-4">
              <Avatar src={avatarUrl ?? undefined} name={displayName || me.email} size="lg" />
              <Button variant="secondary" onClick={() => avatarInput.current?.click()}>
                {t('changeAvatar')}
              </Button>
              <input
                ref={avatarInput}
                type="file"
                accept="image/*"
                className="sr-only"
                onChange={(event) => void changeAvatar(event.target.files?.[0])}
              />
            </div>

            <TextInput
              label={t('displayName')}
              value={displayName}
              maxLength={80}
              onChange={(event) => setDisplayName(event.target.value)}
              onBlur={() => void saveProfile({ display_name: displayName })}
            />
            <TextArea
              label={t('bio')}
              value={bio}
              maxLength={500}
              onChange={(event) => setBio(event.target.value)}
              onBlur={() => void saveProfile({ bio })}
            />
            <TextInput
              label={t('location')}
              value={location}
              maxLength={80}
              onChange={(event) => setLocation(event.target.value)}
              onBlur={() => void saveProfile({ location })}
            />
            {saving ? <p className="text-xs text-muted">{tActions('saving')}</p> : null}
          </Panel>
        ) : null}

        {section === 'privacy' ? (
          <>
            <Panel title={t('privacySection')}>
              <div className="divide-y divide-border">
                <Switch
                  label={t('publicProfile')}
                  description={t('publicProfileDesc')}
                  checked={publicProfile}
                  onChange={(next) => {
                    setPublicProfile(next);
                    void saveProfile({ public_profile: next });
                  }}
                />
              </div>
            </Panel>

            <Panel title={t('dataSection')}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">{t('exportData')}</p>
                  <p className="mt-0.5 text-xs text-muted">{t('exportDataDesc')}</p>
                </div>
                <Button variant="secondary" onClick={() => void requestData('export')}>
                  {tActions('submit')}
                </Button>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
                <div>
                  <p className="text-sm font-medium text-danger">{t('deleteAccount')}</p>
                  <p className="mt-0.5 text-xs text-muted">{t('deleteAccountDesc')}</p>
                </div>
                <Button variant="danger" onClick={() => setConfirmDelete(true)}>
                  {tActions('delete')}
                </Button>
              </div>
            </Panel>
          </>
        ) : null}

        {section === 'notifications' ? (
          <Panel title={t('notificationsSection')}>
            <Switch
              label={t('remixNotify')}
              description={t('remixNotifyDesc')}
              checked={notifyOnRemix}
              onChange={(next) => {
                setNotifyOnRemix(next);
                void savePreferences({ notify_on_remix: next });
              }}
            />
          </Panel>
        ) : null}

        {section === 'display' ? (
          <Panel title={t('displaySection')}>
            <div>
              <OptionGroup
                label={t('themeSection')}
                value={preference}
                onChange={(next: ThemePreference) => {
                  setPreference(next);
                  void savePreferences({ theme: next });
                }}
                options={[
                  {
                    value: 'system',
                    label: tTheme('system'),
                    icon: <IconMonitor className="size-4" />,
                  },
                  { value: 'dark', label: tTheme('dark'), icon: <IconMoon className="size-4" /> },
                  { value: 'light', label: tTheme('light'), icon: <IconSun className="size-4" /> },
                ]}
              />
              <p className="mt-2 text-xs text-muted">{t('themeDesc')}</p>
            </div>

            <div>
              <OptionGroup
                label={t('regionLabel')}
                value={me.region as Region}
                onChange={(next: Region) => {
                  const locale = regionLocale[next];
                  void savePreferences({ region: next, locale });
                  router.replace(pathname, { locale });
                }}
                options={regions.map((value) => ({ value, label: tRegion(value) }))}
              />
              <p className="mt-2 text-xs text-muted">{t('regionDesc')}</p>
            </div>

            <Switch
              label={t('reduceMotion')}
              description={t('reduceMotionDesc')}
              checked={reduceMotion}
              onChange={(next) => {
                setReduceMotion(next);
                void savePreferences({ reduce_motion: next });
              }}
            />
          </Panel>
        ) : null}
      </div>

      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t('deleteConfirmTitle')}
        description={t('deleteConfirmBody')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              {tActions('cancel')}
            </Button>
            <Button variant="danger" onClick={() => void requestData('delete')}>
              {tActions('confirm')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t('deleteAccountDesc')}</p>
      </Dialog>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface p-5">
      <h2 className="mb-4 text-base font-semibold">{title}</h2>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  );
}
