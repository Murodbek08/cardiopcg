import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { IconArrowLeft, IconInfoCircle } from '@tabler/icons-react';
import { Alert, Button, ErrorState, Field, PasswordInput, errorMessage, isApiError, toast, post, PageHeader, Card, CardBody } from '@/shared';
import { useAuthStore } from '@/shared/store/auth';
import { changePassword } from '@/shared/api/session';
import { PasswordStrength } from '../components/password-strength';
import { changePasswordSchema, resetPasswordSchema, type ChangePasswordForm, type ResetPasswordForm } from '../schemas';

/** Doc 01 has no self-service "forgot" endpoint: an administrator issues a one-time link / temporary password. */
export function ForgotPasswordPage() {
  const { t } = useTranslation('auth');
  return (
    <div>
      <Link to="/login" className="mb-6 inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
        <IconArrowLeft size={16} aria-hidden /> {t('forgot.back')}
      </Link>
      <h1 className="text-h1 font-semibold">{t('forgot.title')}</h1>
      <Alert tone="info" className="mt-4">
        <span className="inline-flex items-start gap-2">
          <IconInfoCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
          {t('forgot.body')}
        </span>
      </Alert>
    </div>
  );
}

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token } = useSearch({ strict: false }) as { token?: string };
  const [error, setError] = useState<unknown>(null);
  const { register, handleSubmit, control, setError: setFieldError, formState: { errors, isSubmitting } } = useForm<ResetPasswordForm>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { new_password: '', confirm: '' },
  });
  const pw = useWatch({ control, name: 'new_password' });

  if (!token) {
    return (
      <div>
        <ErrorState error={new Error(t('errors:codes.TOKEN_INVALID_OR_EXPIRED'))} />
        <p className="text-center"><Link to="/login" className="text-sm text-brand-600 hover:underline">{t('auth:forgot.back')}</Link></p>
      </div>
    );
  }
  const onSubmit = handleSubmit(async (v) => {
    setError(null);
    try {
      await post('/auth/reset-password', { token, new_password: v.new_password });
      toast.success(t('auth:change.success'));
      await navigate({ to: '/login', replace: true });
    } catch (e) {
      if (isApiError(e) && e.code === 'WEAK_PASSWORD') setFieldError('new_password', { message: errorMessage(e, t as never) });
      else setError(e);
    }
  });
  return (
    <div>
      <h1 className="text-h1 font-semibold">{t('auth:change.title')}</h1>
      <form onSubmit={onSubmit} noValidate className="mt-6 space-y-4">
        {error ? <Alert tone="danger">{errorMessage(error, t as never)}</Alert> : null}
        <Field label={t('auth:change.new')} error={errors.new_password?.message} required>
          <PasswordInput {...register('new_password')} autoComplete="new-password" />
        </Field>
        <PasswordStrength value={pw} />
        <Field label={t('auth:change.confirm')} error={errors.confirm?.message} required>
          <PasswordInput {...register('confirm')} autoComplete="new-password" />
        </Field>
        <Button type="submit" size="lg" className="w-full" loading={isSubmitting}>{t('auth:change.submit')}</Button>
      </form>
    </div>
  );
}

export function ChangePasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const forced = !!user?.must_change_password;
  const [error, setError] = useState<unknown>(null);
  const schema = useMemo(() => changePasswordSchema(user?.username ?? ''), [user?.username]);
  const { register, handleSubmit, control, setError: setFieldError, formState: { errors, isSubmitting } } = useForm<ChangePasswordForm>({
    resolver: zodResolver(schema),
    defaultValues: { current_password: '', new_password: '', confirm: '' },
  });
  const pw = useWatch({ control, name: 'new_password' });

  const onSubmit = handleSubmit(async (v) => {
    setError(null);
    try {
      await changePassword(v.current_password, v.new_password);
      if (user) setUser({ ...user, must_change_password: false });
      toast.success(t('auth:change.success'), { description: t('auth:change.success_body') });
      await navigate({ to: user?.role === 'admin' ? '/admin' : user?.role === 'doctor' ? '/doctor' : '/nurse', replace: true });
    } catch (e) {
      if (isApiError(e) && e.code === 'WRONG_CURRENT_PASSWORD') setFieldError('current_password', { message: errorMessage(e, t as never) });
      else if (isApiError(e) && e.code === 'WEAK_PASSWORD') setFieldError('new_password', { message: errorMessage(e, t as never) });
      else setError(e);
    }
  });

  const form = (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {forced && <Alert tone="warning">{t('auth:change.forced')}</Alert>}
      {error ? <Alert tone="danger">{errorMessage(error, t as never)}</Alert> : null}
      <Field label={t('auth:change.current')} error={errors.current_password?.message} required>
        <PasswordInput {...register('current_password')} autoComplete="current-password" />
      </Field>
      <Field label={t('auth:change.new')} error={errors.new_password?.message} required>
        <PasswordInput {...register('new_password')} autoComplete="new-password" />
      </Field>
      <PasswordStrength value={pw} />
      <Field label={t('auth:change.confirm')} error={errors.confirm?.message} required>
        <PasswordInput {...register('confirm')} autoComplete="new-password" />
      </Field>
      <div className="flex justify-end gap-2">
        {!forced && (
          <Button variant="outline" onClick={() => window.history.back()}>
            {t('actions.cancel')}
          </Button>
        )}
        <Button type="submit" loading={isSubmitting}>{t('auth:change.submit')}</Button>
      </div>
    </form>
  );

  // Forced mode: no shell (no sidebar), centred card.
  if (forced) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background p-6">
        <Card className="w-full max-w-md">
          <CardBody>
            <h1 className="mb-4 text-h1 font-semibold">{t('auth:change.title')}</h1>
            {form}
          </CardBody>
        </Card>
      </div>
    );
  }
  return (
    <div className="max-w-lg">
      <PageHeader title={t('auth:change.title')} />
      <Card><CardBody>{form}</CardBody></Card>
    </div>
  );
}
