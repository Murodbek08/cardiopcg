import { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { IconWand } from '@tabler/icons-react';
import { Alert, Button, Card, CardBody, CheckboxField, CopyField, Dialog, Field, Input, PageHeader, errorMessage, fieldErrorMap, isApiError } from '@/shared';
import { generatePassword } from '@/shared/lib/password';
import { useCreateUser } from '../api';
import { userCreateSchema, type UserCreateForm } from '../schemas';
import { UserFields } from '../components/user-fields';

export function UserCreatePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const create = useCreateUser();
  const [created, setCreated] = useState<{ id: string; username: string; password: string } | null>(null);
  const [formError, setFormError] = useState<unknown>(null);

  const { register, control, handleSubmit, setValue, setError, formState: { errors } } = useForm<UserCreateForm>({
    resolver: zodResolver(userCreateSchema),
    defaultValues: { username: '', full_name: '', role: 'nurse', email: '', phone: '', specialty: '', license_no: '', department: '', password: generatePassword(), must_change_password: true },
  });
  const role = useWatch({ control, name: 'role' });

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      const res = await create.mutateAsync({
        username: v.username,
        full_name: v.full_name,
        role: v.role,
        email: v.email || null,
        phone: v.phone || null,
        specialty: v.role === 'doctor' ? v.specialty || null : null,
        license_no: v.role === 'doctor' ? v.license_no || null : null,
        department: v.role === 'nurse' ? v.department || null : null,
        password: v.password,
        must_change_password: v.must_change_password,
      });
      setCreated({ id: res.id, username: res.username, password: v.password });
    } catch (e) {
      if (isApiError(e)) {
        const map = fieldErrorMap(e);
        for (const [k, msg] of Object.entries(map)) setError(k as keyof UserCreateForm, { message: msg });
        if (e.code === 'USERNAME_TAKEN') setError('username', { message: errorMessage(e, t as never) });
        else if (e.code === 'EMAIL_TAKEN') setError('email', { message: errorMessage(e, t as never) });
        else if (e.code === 'WEAK_PASSWORD') setError('password', { message: errorMessage(e, t as never) });
        else if (!Object.keys(map).length) setFormError(e);
      } else setFormError(e);
    }
  });

  return (
    <div className="max-w-3xl">
      <PageHeader title={t('admin:users.new')} breadcrumbs={[{ label: t('nav:users'), to: '/admin/users' }, { label: t('admin:users.new') }]} />
      <Card>
        <CardBody>
          <form onSubmit={onSubmit} noValidate className="grid gap-4 sm:grid-cols-2">
            {formError ? <Alert tone="danger" className="sm:col-span-2">{errorMessage(formError, t as never)}</Alert> : null}
            <Field label={t('admin:users.fields.username')} error={errors.username?.message} required hint="a-z, 0-9, . _ -" className="sm:col-span-2">
              <Input {...register('username')} autoComplete="off" autoCapitalize="none" spellCheck={false} />
            </Field>
            <UserFields register={register} control={control} errors={errors} role={role} />
            <div className="sm:col-span-2">
              <Field label={t('admin:users.fields.temp_password')} error={errors.password?.message} required hint={t('admin:users.temp_password_hint')}>
                <Input {...register('password')} autoComplete="new-password" className="font-mono" />
              </Field>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Button type="button" size="sm" variant="outline" onClick={() => setValue('password', generatePassword(), { shouldValidate: true })}>
                  <IconWand size={16} aria-hidden /> {t('admin:users.generate_password')}
                </Button>
                <Controller control={control} name="must_change_password" render={({ field }) => <CheckboxField label={t('admin:users.must_change')} checked={field.value} onCheckedChange={(c) => field.onChange(c === true)} />} />
              </div>
            </div>
            <div className="flex justify-end gap-2 sm:col-span-2">
              <Button variant="outline" onClick={() => void navigate({ to: '/admin/users' })}>{t('actions.cancel')}</Button>
              <Button type="submit" loading={create.isPending}>{t('actions.create')}</Button>
            </div>
          </form>
        </CardBody>
      </Card>

      {/* One-time secret: cannot be dismissed by accident and is never retrievable again. */}
      <Dialog
        open={!!created}
        onOpenChange={() => undefined}
        dismissible={false}
        title={t('admin:users.created_title')}
        description={t('admin:users.created_body')}
        footer={<Button onClick={() => { const id = created?.id; setCreated(null); if (id) void navigate({ to: '/admin/users/$id', params: { id } } as never); }}>{t('actions.close')}</Button>}
      >
        {created && (
          <div className="space-y-3">
            <CopyField label={t('admin:users.fields.username')} value={created.username} />
            <CopyField label={t('admin:users.fields.temp_password')} value={created.password} />
            <Alert tone="warning">{t('admin:users.shown_once')}</Alert>
          </div>
        )}
      </Dialog>
    </div>
  );
}
