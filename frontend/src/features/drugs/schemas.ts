import { z } from 'zod';
import i18n from '@/i18n';
import { atcRegex } from '@/shared/lib/zod-uz';
import type { DrugDetail } from '@/shared/api/types';

const t = (k: string, o?: Record<string, unknown>) => i18n.t(`validation:${k}`, o ?? {}) as string;

const num = z.coerce.number({ error: () => t('number') }).positive({ error: () => t('min_value', { min: 0 }) });

export const drugSchema = z.object({
  inn: z.string().trim().min(2),
  trade_names: z.string(),
  group: z.string().trim().min(2),
  atc_code: z.string().trim().refine((v) => v === '' || atcRegex.test(v), { error: () => t('atc') }),
  forms: z.string(),
  indications_icd10: z.string(),
  dose_rules: z
    .array(
      z
        .object({
          population: z.string().trim().min(1),
          min_dose: num,
          max_dose: num,
          unit: z.string().trim().min(1),
          max_daily: z.union([z.literal(''), num]).optional(),
          note: z.string().optional(),
        })
        .refine((d) => Number(d.min_dose) <= Number(d.max_dose), { path: ['max_dose'], error: () => t('min_less_than_max') }),
    ),
  contraindications: z.array(z.object({ text: z.string().trim().min(2), absolute: z.boolean() })),
  side_effects: z.array(z.object({ text: z.string().trim().min(2), frequency: z.enum(['common', 'uncommon', 'rare']) })),
  interactions: z.array(
    z.object({
      drug_id: z.string().min(1),
      drug_name: z.string().optional(),
      level: z.enum(['minor', 'moderate', 'major', 'contraindicated']),
      mechanism: z.string().trim().min(2),
      recommendation: z.string().trim().min(2),
    }),
  ),
  sources: z.array(z.object({ title: z.string().trim().min(2), url: z.string().trim().refine((v) => /^https?:\/\/\S+$/.test(v), { error: () => t('url') }) })),
});
export type DrugFormValues = z.input<typeof drugSchema>;
export type DrugFormOutput = z.output<typeof drugSchema>;

const split = (s: string) => s.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean);
export const joinList = (a: string[] | undefined) => (a ?? []).join(', ');

export function toFormValues(d?: DrugDetail): DrugFormValues {
  return {
    inn: d?.inn ?? '',
    trade_names: joinList(d?.trade_names),
    group: d?.group ?? '',
    atc_code: d?.atc_code ?? '',
    forms: joinList(d?.forms),
    indications_icd10: joinList(d?.indications_icd10),
    dose_rules: (d?.dose_rules ?? []).map((r) => ({ ...r, max_daily: r.max_daily ?? '', note: r.note ?? '' })),
    contraindications: d?.contraindications ?? [],
    side_effects: d?.side_effects ?? [],
    interactions: d?.interactions ?? [],
    sources: d?.sources ?? [],
  };
}

export function toPayload(v: DrugFormOutput) {
  return {
    inn: v.inn,
    trade_names: split(v.trade_names),
    group: v.group,
    atc_code: v.atc_code || null,
    forms: split(v.forms),
    indications_icd10: split(v.indications_icd10),
    dose_rules: v.dose_rules.map((r) => ({ population: r.population, min_dose: Number(r.min_dose), max_dose: Number(r.max_dose), unit: r.unit, max_daily: r.max_daily === '' || r.max_daily === undefined ? null : Number(r.max_daily), note: r.note || undefined })),
    contraindications: v.contraindications,
    side_effects: v.side_effects,
    interactions: v.interactions,
    sources: v.sources,
  };
}
