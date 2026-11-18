import { z } from 'zod';
import i18n from '@/i18n';
import { phoneRegex, usernameRegex } from '@/shared/lib/zod-uz';
import { checkPassword } from '@/shared/lib/password';

const t = (k: string, o?: Record<string, unknown>) => i18n.t(`validation:${k}`, o ?? {}) as string;


const base = {
  full_name: z.string().trim().min(2).max(160),
  role: z.enum(['admin', 'doctor', 'nurse']),
  email: z.union([z.literal(''), z.email({ error: () => t('email') })]),
  phone: z.union([z.literal(''), z.string().regex(phoneRegex, { error: () => t('phone') })]),
  specialty: z.string().trim().max(120),
  license_no: z.string().trim().max(64),
  department: z.string().trim().max(120),
};

function roleRules(v: { role: string; license_no: string }, ctx: z.RefinementCtx) {
  // Doctors must have a licence number (doc 03, 3.19).
  if (v.role === 'doctor' && !v.license_no.trim()) ctx.addIssue({ code: 'custom', path: ['license_no'], message: t('required') });
}

export const userCreateSchema = z
  .object({
    ...base,
    username: z.string().trim().toLowerCase().regex(usernameRegex, { error: () => t('username') }),
    password: z.string().superRefine((pw, ctx) => {
      const c = checkPassword(pw, 10);
      if (!c.length) ctx.addIssue({ code: 'custom', message: t('min_length', { count: 10 }) });
      else if (!c.case || !c.digit) ctx.addIssue({ code: 'custom', message: t('invalid') });
    }),
    must_change_password: z.boolean(),
  })
  .superRefine(roleRules);
export type UserCreateForm = z.infer<typeof userCreateSchema>;

export const userEditSchema = z
  .object({ ...base, status: z.enum(['active', 'suspended', 'pending']) })
  .superRefine(roleRules);
export type UserEditForm = z.infer<typeof userEditSchema>;
