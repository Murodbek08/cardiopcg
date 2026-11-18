import { useState } from 'react';
import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { Alert, Button, Field, Input, PasswordInput, isApiError } from '@/shared';
import { login } from '@/shared/api/session';
import { safeNext } from '@/shared/lib/url';
import { loginSchema, type LoginForm } from '../schemas';

export function loginErrorKey(e: unknown): { key: string; opts?: Record<string, unknown> } {
  if (!isApiError(e)) return { key: 'login.errors.invalid' };
  if (e.isNetwork) return { key: 'login.errors.network' };
  if (e.status === 423 || e.code === 'ACCOUNT_LOCKED') {
    const until = e.details?.locked_until;
    if (typeof until === 'string') {
      const minutes = Math.max(1, Math.ceil((new Date(until).getTime() - Date.now()) / 60_000));
      return { key: 'login.errors.locked', opts: { minutes } };
    }
    return { key: 'login.errors.locked_generic' };
  }
  if (e.status === 403 || e.code === 'ACCOUNT_SUSPENDED') return { key: 'login.errors.suspended' };
  if (e.status === 429) return { key: 'login.errors.rate_limited' };
  // 401 and anything else: never reveal which field was wrong
  return { key: 'login.errors.invalid' };
}

export function LoginPage() {
  const { t } = useTranslation('auth');
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { next?: string };
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register, handleSubmit, resetField, setFocus, formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema), defaultValues: { username: '', password: '' } });

  const onSubmit = handleSubmit(async (v) => {
    setServerError(null);
    try {
      const res = await login(v.username, v.password);
      if (res.user.must_change_password) {
        await navigate({ to: '/change-password', replace: true });
        return;
      }
      const home = res.user.role === 'admin' ? '/admin' : res.user.role === 'doctor' ? '/doctor' : '/nurse';
      await navigate({ to: safeNext(search.next, home), replace: true });
    } catch (e) {
      const { key, opts } = loginErrorKey(e);
      setServerError(t(key, opts ?? {}));
      resetField('password'); // clear password after a failed attempt
      setFocus('password');
    }
  });

  return (
    <div>
      <h1 className="text-h1 font-semibold">{t('login.title')}</h1>
      <p className="mt-1 text-sm text-muted">{t('login.subtitle')}</p>
      <form onSubmit={onSubmit} noValidate className="mt-6 space-y-4">
        {serverError && <Alert tone="danger">{serverError}</Alert>}
        <Field label={t('login.username')} error={errors.username?.message} required>
          <Input {...register('username')} autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} autoFocus disabled={isSubmitting} />
        </Field>
        <Field label={t('login.password')} error={errors.password?.message} required>
          <PasswordInput {...register('password')} autoComplete="current-password" capsWarning disabled={isSubmitting} />
        </Field>
        <Button type="submit" size="lg" className="w-full" loading={isSubmitting}>
          {t('login.submit')}
        </Button>
        <p className="text-center text-sm">
          <Link to="/forgot-password" className="text-brand-600 hover:underline dark:text-brand-300">
            {t('login.forgot')}
          </Link>
        </p>
      </form>
    </div>
  );
}
