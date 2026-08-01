'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { IconShield } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { adminApi } from '@/lib/api/admin-client';

export function AdminLoginForm({ locale }: { locale: string }) {
  const t = useTranslations('admin');
  const tAuth = useTranslations('auth');

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      await adminApi.post('/v1/admin/auth/login', { email, password });
      // A full navigation, not a router push: the server layout has to read the
      // newly set console cookie before anything under /admin renders.
      window.location.assign(`/${locale}/admin`);
    } catch {
      // One message for a wrong password and for a valid account without console
      // access, so the form cannot be used to enumerate operators.
      setFailed(true);
      setBusy(false);
    }
  };

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <form
        onSubmit={submit}
        className="w-full max-w-[420px] rounded-[var(--radius-lg)] border border-border bg-surface p-7"
      >
        <span className="grid size-11 place-items-center rounded-full bg-primary/12 text-primary">
          <IconShield className="size-5" />
        </span>

        <h1 className="mt-4 text-xl font-semibold">{t('loginTitle')}</h1>
        <p className="mt-1.5 text-sm text-muted">{t('loginSubtitle')}</p>

        <div className="mt-6 flex flex-col gap-4">
          <TextInput
            label={tAuth('email')}
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <TextInput
            label={tAuth('password')}
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />

          {failed ? <ErrorNotice title={t('loginFailed')} /> : null}

          <Button type="submit" size="lg" fullWidth loading={busy}>
            {t('loginButton')}
          </Button>
        </div>
      </form>
    </main>
  );
}
