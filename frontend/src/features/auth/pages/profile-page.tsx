import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { Button, Card, CardBody, CardHeader, ConfirmDialog, ErrorState, Field, Input, PageHeader, Select, SkeletonRows, get, patch, post, qk, toast } from '@/shared';
import type { Me } from '@/shared/api/types';
import { useAuthStore } from '@/shared/store/auth';
import { setLanguage } from '@/i18n';
import { profileSchema, type ProfileForm } from '../schemas';

export function ProfilePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const setUser = useAuthStore((s) => s.setUser);
  const user = useAuthStore((s) => s.user);
  const [confirmAll, setConfirmAll] = useState(false);
  const me = useQuery({ queryKey: qk.me, queryFn: () => get<Me>('/auth/me') });
  const { register, handleSubmit, control, reset, formState: { errors, isDirty } } = useForm<ProfileForm>({
    resolver: zodResolver(profileSchema),
    defaultValues: { full_name: '', phone: '', email: '', locale: 'uz' },
  });
  useEffect(() => {
    if (me.data) reset({ full_name: me.data.full_name, phone: me.data.phone ?? '', email: me.data.email ?? '', locale: me.data.locale });
  }, [me.data, reset]);

  const save = useMutation({
    mutationFn: (v: ProfileForm) => patch<Me>('/auth/me', { full_name: v.full_name, phone: v.phone || null, email: v.email || null, locale: v.locale }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: qk.me });
      if (user) setUser({ ...user, full_name: v.full_name, locale: v.locale });
      setLanguage(v.locale);
      toast.success(t('actions.save'));
    },
  });
  const logoutAll = useMutation({
    mutationFn: () => post('/auth/logout-all'),
    onSuccess: () => {
      setConfirmAll(false);
      toast.success(t('nav:profile'));
    },
  });

  if (me.isLoading) return <SkeletonRows rows={5} />;
  if (me.isError) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />;

  return (
    <div className="max-w-2xl space-y-6">
      <PageHeader title={t('nav:profile')} description={me.data ? `${me.data.username} - ${t(`role.${me.data.role}`)}` : undefined} />
      <Card>
        <CardHeader title={t('nav:profile')} />
        <CardBody>
          <form onSubmit={handleSubmit((v) => save.mutate(v))} noValidate className="grid gap-4 sm:grid-cols-2">
            <Field label="F.I.Sh." error={errors.full_name?.message} required className="sm:col-span-2">
              <Input {...register('full_name')} autoComplete="name" />
            </Field>
            <Field label="Telefon" error={errors.phone?.message} hint="+998901234567">
              <Input {...register('phone')} autoComplete="tel" inputMode="tel" />
            </Field>
            <Field label="Email" error={errors.email?.message}>
              <Input {...register('email')} type="email" autoComplete="email" />
            </Field>
            <Field label={t('language.label')}>
              <Controller
                control={control}
                name="locale"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange} options={[{ value: 'uz', label: t('language.uz') }, { value: 'ru', label: t('language.ru') }, { value: 'en', label: t('language.en') }]} />
                )}
              />
            </Field>
            <div className="flex items-end justify-end sm:col-span-2">
              <Button type="submit" loading={save.isPending} disabled={!isDirty}>{t('actions.save')}</Button>
            </div>
          </form>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Sessiyalar" description="Barcha qurilmalardagi sessiyalarni yopish" />
        <CardBody>
          <Button variant="outline" onClick={() => setConfirmAll(true)}>Barcha sessiyalardan chiqish</Button>
        </CardBody>
      </Card>
      <ConfirmDialog
        open={confirmAll}
        onOpenChange={setConfirmAll}
        title="Barcha sessiyalardan chiqish"
        description="Boshqa qurilmalardagi sessiyalar bekor qilinadi."
        danger
        loading={logoutAll.isPending}
        onConfirm={() => logoutAll.mutateAsync()}
      />
    </div>
  );
}
