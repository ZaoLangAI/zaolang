'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextInput } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { ApiError } from '@/lib/api/errors';
import { defaultRegion } from '@/i18n/routing';

type Mode = 'signIn' | 'signUp';

export function LoginDialog() {
  const t = useTranslations('auth');
  const tActions = useTranslations('actions');
  const locale = useLocale();
  const { loginPrompt, closeLogin, signIn, signUp } = useSession();

  const [mode, setMode] = useState<Mode>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [handle, setHandle] = useState('');
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setFieldErrors({});
    try {
      if (mode === 'signIn') {
        await signIn(email, password);
      } else {
        await signUp({
          email,
          password,
          display_name: displayName,
          handle,
          region: defaultRegion,
          locale,
          age_confirmed: ageConfirmed,
        });
      }
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFieldErrors(caught.fieldErrors);
        setError(caught.isAuthRequired ? t('invalidCredentials') : caught.message);
      } else {
        setError(t('invalidCredentials'));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const isSignUp = mode === 'signUp';

  return (
    <Dialog
      open={loginPrompt.open}
      onClose={closeLogin}
      title={isSignUp ? t('signUpTitle') : t('signInTitle')}
      description={
        // When the dialog was opened by a blocked action, name the action so
        // the user knows what will resume.
        loginPrompt.label ?? (isSignUp ? t('signUpSubtitle') : t('signInSubtitle'))
      }
      size="sm"
    >
      <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
        {error ? <ErrorNotice title={error} /> : null}

        <TextInput
          label={t('email')}
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          error={fieldErrors.email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <TextInput
          label={t('password')}
          type="password"
          name="password"
          autoComplete={isSignUp ? 'new-password' : 'current-password'}
          required
          value={password}
          error={fieldErrors.password}
          onChange={(event) => setPassword(event.target.value)}
        />

        {isSignUp ? (
          <>
            <TextInput
              label={t('displayName')}
              name="display_name"
              required
              value={displayName}
              error={fieldErrors.display_name}
              onChange={(event) => setDisplayName(event.target.value)}
            />
            <TextInput
              label={t('handle')}
              name="handle"
              required
              value={handle}
              error={fieldErrors.handle}
              onChange={(event) => setHandle(event.target.value)}
            />
            <label className="flex items-start gap-2 text-xs text-muted">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-[var(--primary)]"
                checked={ageConfirmed}
                onChange={(event) => setAgeConfirmed(event.target.checked)}
              />
              <span>18+</span>
            </label>
          </>
        ) : null}

        <Button type="submit" size="lg" fullWidth loading={submitting}>
          {isSignUp ? t('signUp') : t('signIn')}
        </Button>

        <div className="flex items-center justify-between">
          <Button
            variant="link"
            size="sm"
            onClick={() => {
              setMode(isSignUp ? 'signIn' : 'signUp');
              setError(null);
              setFieldErrors({});
            }}
          >
            {isSignUp ? t('toSignIn') : t('toSignUp')}
          </Button>
          <Button variant="ghost" size="sm" onClick={closeLogin}>
            {tActions('cancel')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
