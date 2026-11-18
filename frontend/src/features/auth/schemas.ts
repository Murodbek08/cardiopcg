import { z } from 'zod';
import i18n from '@/i18n';
import { usernameRegex, phoneRegex } from '@/shared/lib/zod-uz';
import { checkPassword, PASSWORD_MIN_LENGTH } from '@/shared/lib/password';

const t = (k: string, o?: Record<string, unknown>) => i18n.t(`validation:${k}`, o ?? {}) as string;

export const loginSchema = z.object({
  username: z.string().trim().toLowerCase().regex(usernameRegex, { error: () => t('username') }),
  password: z.string().min(1),
});
export type LoginForm = z.infer<typeof loginSchema>;

/** Strong password rule set (doc 03, 3.3). The server additionally enforces zxcvbn >= 3 and history. */
export const newPasswordField = z
  .string()
  .superRefine((pw, ctx) => {
    const c = checkPassword(pw, PASSWORD_MIN_LENGTH);
    if (!c.length) ctx.addIssue({ code: 'custom', message: t('min_length', { count: PASSWORD_MIN_LENGTH }) });
    else if (!c.case || !c.digit || !c.special) ctx.addIssue({ code: 'custom', message: t('invalid') });
  });

export const changePasswordSchema = (username: string) =>
  z
    .object({
      current_password: z.string().min(1),
      new_password: newPasswordField,
      confirm: z.string().min(1),
    })
    .superRefine((v, ctx) => {
      if (v.new_password !== v.confirm) ctx.addIssue({ code: 'custom', path: ['confirm'], message: t('password_mismatch') });
      if (v.new_password && v.new_password === v.current_password) ctx.addIssue({ code: 'custom', path: ['new_password'], message: t('password_same_as_old') });
      if (username && v.new_password.toLowerCase().includes(username.toLowerCase())) ctx.addIssue({ code: 'custom', path: ['new_password'], message: t('password_contains_username') });
    });
export type ChangePasswordForm = { current_password: string; new_password: string; confirm: string };

export const resetPasswordSchema = z
  .object({ new_password: newPasswordField, confirm: z.string().min(1) })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], error: () => t('password_mismatch') });
export type ResetPasswordForm = z.infer<typeof resetPasswordSchema>;

export const profileSchema = z.object({
  full_name: z.string().trim().min(2).max(80),
  phone: z.string().trim().refine((v) => v === '' || phoneRegex.test(v), { error: () => t('phone') }),
  email: z.string().trim().refine((v) => v === '' || z.email().safeParse(v).success, { error: () => t('email') }),
  locale: z.enum(['uz', 'ru', 'en']),
});
export type ProfileForm = z.infer<typeof profileSchema>;
