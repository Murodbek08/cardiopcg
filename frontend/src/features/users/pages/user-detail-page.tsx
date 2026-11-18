import { useEffect, useState } from 'react';
import { useNavigate, useParams } from '@tanstack/react-router';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { IconKey, IconLockOpen, IconUserOff, IconUserCheck, IconTrash } from '@tabler/icons-react';
import {
  Alert, Button, Card, CardBody, CardHeader, ConfirmDialog, CopyField, Dialog, ErrorState, Field, PageHeader, Select, SkeletonRows, StatusBadge,
  errorMessage, formatDateTime, isApiError, toast,
} from '@/shared';
import { useAuthStore } from '@/shared/store/auth';
import type { ResetPasswordResult } from '@/shared/api/types';
import { useDeleteUser, useUpdateUser, useUser, useUserAction, type UserAction } from '../api';
import { userEditSchema, type UserEditForm } from '../schemas';
import { UserFields } from '../components/user-fields';

export function UserDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams({ strict: false }) as { id: string };
  const navigate = useNavigate();
  const me = useAuthStore((s) => s.user);
  const q = useUser(id);
  const update = useUpdateUser(id);
  const action = useUserAction(id);
  const del = useDeleteUser(id);
  const [confirm, setConfirm] = useState<UserAction | 'delete' | null>(null);
  const [secret, setSecret] = useState<ResetPasswordResult | null>(null);
  const [formError, setFormError] = useState<unknown>(null);
  const isSelf = me?.id === id;

  const { register, control, handleSubmit, reset, formState: { errors, isDirty } } = useForm<UserEditForm>({
    resolver: zodResolver(userEditSchema),
    defaultValues: { full_name: '', role: 'nurse', email: '', phone: '', specialty: '', license_no: '', department: '', status: 'active' },
  });
  const role = useWatch({ control, name: 'role' });

  useEffect(() => {
    const u = q.data;
    if (u) reset({ full_name: u.full_name, role: u.role, email: u.email ?? '', phone: u.phone ?? '', specialty: u.specialty ?? '', license_no: u.license_no ?? '', department: u.department ?? '', status: u.status });
  }, [q.data, reset]);

  if (q.isLoading) return <SkeletonRows rows={6} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const user = q.data!;

  const onSave = handleSubmit(async (v) => {
    setFormError(null);
    try {
      await update.mutateAsync({
        full_name: v.full_name,
        role: v.role,
        status: v.status,
        email: v.email || null,
        phone: v.phone || null,
        specialty: v.role === 'doctor' ? v.specialty || null : null,
        license_no: v.role === 'doctor' ? v.license_no || null : null,
        department: v.role === 'nurse' ? v.department || null : null,
      });
      toast.success(t('actions.save'));
    } catch (e) {
      setFormError(e);
    }
  });

  const run = async (a: UserAction | 'delete', reason?: string) => {
    void reason;
    try {
      if (a === 'delete') {
        await del.mutateAsync();
        toast.success(t('admin:users.deleted'));
        void navigate({ to: '/admin/users' });
      } else {
        const res = await action.mutateAsync(a);
        if (a === 'reset-password' && res) setSecret(res);
        else toast.success(t(`admin:users.actions.${a}_done`));
      }
      setConfirm(null);
    } catch (e) {
      setConfirm(null);
      toast.error(isApiError(e) ? errorMessage(e, t as never) : t('errors:unknown'));
    }
  };

  const locked = !!user.locked_until && new Date(user.locked_until) > new Date();
  const selfTip = isSelf ? t('admin:users.self_locked') : undefined;

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title={user.full_name}
        description={<span className="inline-flex flex-wrap items-center gap-2"><span className="font-mono-num">{user.username}</span> <StatusBadge kind="user" value={user.status} /> {locked && <span className="text-danger-500">{t('admin:users.locked')}</span>}</span>}
        breadcrumbs={[{ label: t('nav:users'), to: '/admin/users' }, { label: user.username }]}
      />
      <Card>
        <CardHeader title={t('admin:users.profile')} description={`${t('admin:users.fields.last_login')}: ${formatDateTime(user.last_login_at)}`} />
        <CardBody>
          <form onSubmit={onSave} noValidate className="grid gap-4 sm:grid-cols-2">
            {formError ? <Alert tone="danger" className="sm:col-span-2">{errorMessage(formError, t as never)}</Alert> : null}
            <UserFields register={register} control={control} errors={errors} role={role} disableRole={isSelf} />
            <Field label={t('admin:users.fields.status')}>
              <Controller control={control} name="status" render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange} disabled={isSelf} options={(['active', 'suspended', 'pending'] as const).map((s) => ({ value: s, label: t(`admin:users.status.${s}`) }))} />
              )} />
            </Field>
            <div className="flex items-end justify-end sm:col-span-2">
              <Button type="submit" loading={update.isPending} disabled={!isDirty}>{t('actions.save')}</Button>
            </div>
          </form>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t('admin:users.security')} />
        <CardBody className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setConfirm('reset-password')}><IconKey size={18} aria-hidden /> {t('admin:users.actions.reset-password')}</Button>
          {locked && <Button variant="outline" onClick={() => void run('unlock')}><IconLockOpen size={18} aria-hidden /> {t('admin:users.actions.unlock')}</Button>}
          {user.status === 'suspended' ? (
            <Button variant="outline" onClick={() => void run('activate')}><IconUserCheck size={18} aria-hidden /> {t('admin:users.actions.activate')}</Button>
          ) : (
            <Button variant="outline" disabled={isSelf} title={selfTip} onClick={() => setConfirm('suspend')}><IconUserOff size={18} aria-hidden /> {t('admin:users.actions.suspend')}</Button>
          )}
          <Button variant="danger" disabled={isSelf} title={selfTip} onClick={() => setConfirm('delete')}><IconTrash size={18} aria-hidden /> {t('actions.delete')}</Button>
        </CardBody>
      </Card>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={confirm ? t(`admin:users.confirm.${confirm}.title`) : ''}
        description={confirm ? t(`admin:users.confirm.${confirm}.body`) : undefined}
        danger={confirm === 'delete' || confirm === 'suspend'}
        loading={action.isPending || del.isPending}
        onConfirm={() => (confirm ? run(confirm) : undefined)}
      />
      <Dialog
        open={!!secret}
        onOpenChange={() => undefined}
        dismissible={false}
        title={t('admin:users.reset_title')}
        description={t('admin:users.shown_once')}
        footer={<Button onClick={() => setSecret(null)}>{t('actions.close')}</Button>}
      >
        <div className="space-y-3">
          {secret?.temp_password && <CopyField label={t('admin:users.fields.temp_password')} value={secret.temp_password} />}
          {secret?.reset_token && <CopyField label={t('admin:users.reset_link')} value={`${window.location.origin}/reset-password?token=${secret.reset_token}`} />}
          <Alert tone="warning">{t('admin:users.shown_once')}</Alert>
        </div>
      </Dialog>
    </div>
  );
}
