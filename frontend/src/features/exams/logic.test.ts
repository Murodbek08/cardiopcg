import { describe, expect, it } from 'vitest';
import {
  abnormalProbability, acceptRequirement, checkAudioDuration, conclusionLocked, evaluateQuality, featureRows, itemInteractionLevel, signBlockers, stageIndex, suggestAgreement, vitalWarnings, vitalsSchema,
} from './logic';
import { bmi, bmiBand, createPatientSchema, emptyPatient } from '@/features/patients/schemas';
import type { AnalysisResult } from '@/shared/api/types';

describe('vitals validation (hard bounds block, typical ranges only warn)', () => {
  it('accepts empty and legal values, converts strings', () => {
    expect(vitalsSchema.safeParse({}).success).toBe(true);
    const r = vitalsSchema.parse({ bp_systolic: '120', bp_diastolic: '80', heart_rate_bpm: '' });
    expect(r.bp_systolic).toBe(120);
    expect(r.heart_rate_bpm).toBeUndefined();
  });
  it('rejects values outside the backend bounds and inverted pressure', () => {
    expect(vitalsSchema.safeParse({ spo2_pct: 101 }).success).toBe(false);
    expect(vitalsSchema.safeParse({ heart_rate_bpm: 10 }).success).toBe(false);
    expect(vitalsSchema.safeParse({ bp_systolic: 80, bp_diastolic: 90 }).success).toBe(false);
  });
  it('warns (does not block) for atypical but legal values', () => {
    expect(vitalWarnings({ heart_rate_bpm: 180, spo2_pct: 85, bp_systolic: 120 })).toEqual(['heart_rate_bpm', 'spo2_pct']);
    expect(vitalWarnings({ heart_rate_bpm: 72 })).toEqual([]);
    expect(vitalsSchema.safeParse({ heart_rate_bpm: 180, spo2_pct: 85 }).success).toBe(true);
  });
});

describe('recording quality', () => {
  const base = { validation_report: {}, status: 'validated' };
  it('good / low / unusable', () => {
    expect(evaluateQuality({ ...base, snr_db: 20, quality_score: 0.8 }).level).toBe('good');
    expect(evaluateQuality({ ...base, snr_db: 6, quality_score: 0.8 }).level).toBe('low');
    expect(evaluateQuality({ ...base, snr_db: 3, quality_score: 0.8 }).level).toBe('unusable');
    expect(evaluateQuality({ ...base, snr_db: 20, quality_score: 0.3 }).level).toBe('low');
    expect(evaluateQuality({ ...base, snr_db: 20, quality_score: 0.8, validation_report: { warnings: ['clipping'] } }).level).toBe('low');
    expect(evaluateQuality({ status: 'rejected', snr_db: 20, quality_score: 1, validation_report: {} }).level).toBe('unusable');
  });
  it('duration limits', () => {
    expect(checkAudioDuration(3)).toBe('short');
    expect(checkAudioDuration(200)).toBe('long');
    expect(checkAudioDuration(15)).toBeNull();
  });
});

describe('drug safety rules (UI blocking)', () => {
  const item = (o: object) => ({ allergy_warning: false, safety_pending: false, interaction_warnings: [] as unknown[], ...o });
  it('free accept for clean items', () => expect(acceptRequirement(item({}))).toBe('free'));
  it('allergy conflict forces a written reason', () => expect(acceptRequirement(item({ allergy_warning: true }))).toBe('reason'));
  it('major / contraindicated interaction forces a reason; minor does not', () => {
    expect(acceptRequirement(item({ interaction_warnings: [{ level: 'contraindicated' }] }))).toBe('reason');
    expect(acceptRequirement(item({ interaction_warnings: [{ level: 'major' }] }))).toBe('reason');
    expect(acceptRequirement(item({ interaction_warnings: [{ level: 'minor' }] }))).toBe('free');
  });
  it('pending safety check blocks acceptance entirely', () => expect(acceptRequirement(item({ safety_pending: true, allergy_warning: true }))).toBe('blocked'));
  it('picks the most severe interaction level', () => {
    expect(itemInteractionLevel({ interaction_warnings: [{ level: 'minor' }, { level: 'major' }, { level: 'moderate' }] })).toBe('major');
    expect(itemInteractionLevel({ interaction_warnings: [] })).toBeNull();
  });
});

describe('conclusion sign blockers', () => {
  const ok = { diagnosis_text: 'Mitral klapan yetishmovchiligi, o\'rtacha daraja.', recommendations: 'Exo-KG', icd10_codes: ['I34.0'], agreement_with_ai: 'agree' as const, disagreement_reason: '', follow_up_date: null };
  it('passes when everything is complete', () => expect(signBlockers(ok, [{ status: 'approved' }, { status: 'rejected' }], true, '2026-11-18')).toEqual([]));
  it('reports each missing piece', () => {
    expect(signBlockers({ ...ok, diagnosis_text: 'qisqa' }, [], true, '2026-11-18')).toContain('diagnosis_short');
    expect(signBlockers({ ...ok, icd10_codes: [] }, [], true, '2026-11-18')).toContain('no_icd');
    expect(signBlockers({ ...ok, recommendations: ' ' }, [], true, '2026-11-18')).toContain('recommendations');
    expect(signBlockers(ok, [{ status: 'suggested' }], true, '2026-11-18')).toContain('pending_items');
    expect(signBlockers(ok, [], false, '2026-11-18')).toContain('no_ai');
  });
  it('disagreement needs a reason; follow-up must be in the future', () => {
    expect(signBlockers({ ...ok, agreement_with_ai: 'disagree' }, [], true, '2026-11-18')).toContain('reason');
    expect(signBlockers({ ...ok, agreement_with_ai: 'partial', disagreement_reason: 'sabab' }, [], true, '2026-11-18')).not.toContain('reason');
    expect(signBlockers({ ...ok, follow_up_date: '2026-11-18' }, [], true, '2026-11-18')).toContain('followup_past');
    expect(signBlockers({ ...ok, follow_up_date: '2026-12-01' }, [], true, '2026-11-18')).not.toContain('followup_past');
  });
  it('locks after signing / amendment', () => {
    expect(conclusionLocked({ status: 'signed' }, 'completed')).toBe(true);
    expect(conclusionLocked({ status: 'draft' }, 'in_review')).toBe(false);
    expect(conclusionLocked(null, 'completed')).toBe(true);
  });
  it('suggests agreement from class equality', () => {
    expect(suggestAgreement('murmur', 'murmur')).toBe('agree');
    expect(suggestAgreement('murmur', 'normal')).toBe('disagree');
  });
});

describe('AI result helpers', () => {
  const a = { class_probs: { normal: 0.09, murmur: 0.84 }, pcg_class: 'murmur', confidence: 0.84 } as unknown as AnalysisResult;
  it('derives an abnormality probability from class probabilities (no fabricated risk score)', () => {
    expect(abnormalProbability(a)).toBe(91);
    expect(abnormalProbability(null)).toBeNull();
    expect(abnormalProbability({ ...a, class_probs: {} as never, pcg_class: 'normal', confidence: 0.9 })).toBe(10);
  });
  it('flags out-of-range features and leaves missing ones neutral', () => {
    const rows = featureRows({ heart_rate_bpm: 130, systole_ms: 300, murmur_timing: 'systolic', murmur_grade: 3 } as unknown as AnalysisResult);
    const by = Object.fromEntries(rows.map((r) => [r.key, r]));
    expect(by.heart_rate_bpm!.abnormal).toBe(true);
    expect(by.systole_ms!.abnormal).toBe(false);
    expect(by.hr_variability_ms!.value).toBeNull();
    expect(by.murmur_timing!.abnormal).toBe(true);
  });
  it('maps pipeline stages to an index', () => {
    expect(stageIndex('classifying')).toBeGreaterThan(stageIndex('segmenting'));
    expect(stageIndex(undefined)).toBe(0);
    expect(stageIndex('nope')).toBe(0);
  });
});

describe('patient form rules', () => {
  const valid = { ...emptyPatient, last_name: 'Karimov', first_name: 'Aziz', birth_date: '1975-04-12', ai_consent: true };
  it('accepts a minimal valid patient', () => expect(createPatientSchema.safeParse(valid).success).toBe(true));
  it('requires consent on creation', () => expect(createPatientSchema.safeParse({ ...valid, ai_consent: false }).success).toBe(false));
  it('rejects future birth date, bad phone and out-of-range anthropometry', () => {
    expect(createPatientSchema.safeParse({ ...valid, birth_date: '2999-01-01' }).success).toBe(false);
    expect(createPatientSchema.safeParse({ ...valid, phone: '12345' }).success).toBe(false);
    expect(createPatientSchema.safeParse({ ...valid, phone: '+998901234567' }).success).toBe(true);
    expect(createPatientSchema.safeParse({ ...valid, height_cm: 20 }).success).toBe(false);
    expect(createPatientSchema.safeParse({ ...valid, weight_kg: 500 }).success).toBe(false);
  });
  it('computes BMI and bands', () => {
    expect(bmi(176, 84.5)).toBe(27.3);
    expect(bmi('', 80)).toBeNull();
    expect(bmiBand(17)).toBe('under');
    expect(bmiBand(22)).toBe('normal');
    expect(bmiBand(27)).toBe('over');
    expect(bmiBand(33)).toBe('obese');
  });
});
