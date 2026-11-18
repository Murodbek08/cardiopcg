import { z } from 'zod';
import i18n from '@/i18n';
import { phoneRegex } from '@/shared/lib/zod-uz';

const t = (k: string, o?: Record<string, unknown>) => i18n.t(`validation:${k}`, o ?? {}) as string;
const numOpt = (min: number, max: number) =>
  z.preprocess((v) => (v === '' || v == null || Number.isNaN(v) ? undefined : Number(v)), z.number({ error: () => t('number') }).min(min, { error: () => t('range', { min, max }) }).max(max, { error: () => t('range', { min, max }) }).optional());
const phoneOpt = z.string().trim().refine((v) => v === '' || phoneRegex.test(v), { error: () => t('phone') });

export const patientSchema = z.object({
  last_name: z.string().trim().min(2).max(60),
  first_name: z.string().trim().min(2).max(60),
  middle_name: z.string().trim().max(80),
  birth_date: z
    .string()
    .min(1)
    .refine((v) => v <= new Date().toISOString().slice(0, 10), { error: () => 'Kelajak sanasi bo\'lishi mumkin emas' })
    .refine((v) => v >= '1900-01-01' && new Date().getFullYear() - Number(v.slice(0, 4)) <= 120, { error: () => 'Tug\'ilgan sana noto\'g\'ri' }),
  gender: z.enum(['male', 'female']),
  blood_group: z.enum(['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'unknown']),
  phone: phoneOpt,
  address: z.string().trim().max(1000),
  national_id: z.string().trim().refine((v) => v === '' || (v.length >= 5 && v.length <= 32), { error: () => t('invalid') }),
  height_cm: numOpt(30, 250),
  weight_kg: numOpt(1, 400),
  emergency_contact_name: z.string().trim().max(160),
  emergency_contact_phone: phoneOpt,
  primary_doctor_id: z.string(),
  notes: z.string().max(5000),
  ai_consent: z.boolean(),
  allergies: z.array(z.object({ substance: z.string().trim().min(1), reaction: z.string().trim(), severity: z.enum(['mild', 'moderate', 'severe', 'anaphylaxis']) })),
  medications: z.array(z.object({ drug_name: z.string().trim().min(1), dose: z.string().trim(), frequency: z.string().trim() })),
  history: z.array(z.object({ kind: z.enum(['cardiac', 'chronic', 'surgical', 'family', 'habit', 'other']), title: z.string().trim().min(1), icd10_code: z.string().trim() })),
});
export type PatientFormInput = z.input<typeof patientSchema>;
export type PatientFormOutput = z.output<typeof patientSchema>;

export const createPatientSchema = patientSchema.refine((v) => v.ai_consent === true, { path: ['ai_consent'], error: () => t('required') });

export function bmi(heightCm: unknown, weightKg: unknown): number | null {
  const h = Number(heightCm);
  const w = Number(weightKg);
  if (!h || !w || h < 30 || w < 1) return null;
  return Math.round((w / (h / 100) ** 2) * 10) / 10;
}

export function bmiBand(v: number): 'under' | 'normal' | 'over' | 'obese' {
  return v < 18.5 ? 'under' : v < 25 ? 'normal' : v < 30 ? 'over' : 'obese';
}

export const emptyPatient: PatientFormInput = {
  last_name: '', first_name: '', middle_name: '', birth_date: '', gender: 'male', blood_group: 'unknown', phone: '', address: '', national_id: '',
  height_cm: '' as unknown as number, weight_kg: '' as unknown as number, emergency_contact_name: '', emergency_contact_phone: '', primary_doctor_id: '', notes: '', ai_consent: false,
  allergies: [], medications: [], history: [],
};

/** Body for POST/PATCH /patients: empty strings become null. */
export function toPatientBody(v: PatientFormOutput) {
  const n = (s: string) => (s.trim() === '' ? null : s.trim());
  return {
    last_name: v.last_name, first_name: v.first_name, middle_name: n(v.middle_name), birth_date: v.birth_date, gender: v.gender, blood_group: v.blood_group,
    phone: n(v.phone), address: n(v.address), national_id: n(v.national_id), height_cm: v.height_cm ?? null, weight_kg: v.weight_kg ?? null,
    emergency_contact_name: n(v.emergency_contact_name), emergency_contact_phone: n(v.emergency_contact_phone), primary_doctor_id: v.primary_doctor_id || null, notes: n(v.notes), ai_consent: v.ai_consent,
  };
}
