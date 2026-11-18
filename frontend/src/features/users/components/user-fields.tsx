import type { Control, FieldErrors, UseFormRegister, FieldValues, Path } from 'react-hook-form';
import { Controller } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Field, Input, RadioGroup, RadioItem } from '@/shared';
import type { Role } from '@/shared/api/types';

interface Props<T extends FieldValues> {
  register: UseFormRegister<T>;
  control: Control<T>;
  errors: FieldErrors<T>;
  role: Role;
  disableRole?: boolean;
}

/** Shared identity/role/contact block used by both create and edit forms. */
export function UserFields<T extends FieldValues>({ register, control, errors, role, disableRole }: Props<T>) {
  const { t } = useTranslation('admin');
  const err = (name: string) => (errors as Record<string, { message?: string } | undefined>)[name]?.message;
  const reg = (name: string) => register(name as Path<T>);
  return (
    <>
      <Field label={t('users.fields.full_name')} error={err('full_name')} required className="sm:col-span-2">
        <Input {...reg('full_name')} autoComplete="off" />
      </Field>
      <div className="sm:col-span-2">
        <p className="mb-1.5 text-sm font-medium">{t('users.fields.role')}</p>
        <Controller
          control={control}
          name={'role' as Path<T>}
          render={({ field }) => (
            <RadioGroup value={field.value as string} onValueChange={field.onChange} aria-label={t('users.fields.role')} disabled={disableRole}>
              {(['admin', 'doctor', 'nurse'] as Role[]).map((r) => (
                <RadioItem key={r} value={r} label={t(`common:role.${r}`)} />
              ))}
            </RadioGroup>
          )}
        />
        {disableRole && <p className="mt-1 text-xs text-muted">{t('users.self_locked')}</p>}
      </div>
      <Field label="Email" error={err('email')}>
        <Input {...reg('email')} type="email" autoComplete="off" />
      </Field>
      <Field label={t('users.fields.phone')} error={err('phone')} hint="+998901234567">
        <Input {...reg('phone')} inputMode="tel" autoComplete="off" />
      </Field>
      {role === 'doctor' && (
        <>
          <Field label={t('users.fields.specialty')} error={err('specialty')}>
            <Input {...reg('specialty')} />
          </Field>
          <Field label={t('users.fields.license_no')} error={err('license_no')} required>
            <Input {...reg('license_no')} />
          </Field>
        </>
      )}
      {role === 'nurse' && (
        <Field label={t('users.fields.department')} error={err('department')}>
          <Input {...reg('department')} />
        </Field>
      )}
    </>
  );
}
