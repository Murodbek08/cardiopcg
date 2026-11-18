import { z } from 'zod';
import type { AnalysisResult, Conclusion, ExamStatus, PrescriptionItem, Recording } from '@/shared/api/types';

// ------------------------------------------------------------------ vitals (doc 03 3.13 + backend hard bounds)
const optNum = (min: number, max: number) =>
  z.preprocess((v) => (v === '' || v === null || v === undefined || Number.isNaN(v) ? undefined : Number(v)), z.number().min(min).max(max).optional());

/** Hard bounds are the backend's limits (blocking); "typical" ranges only produce warnings. */
export const vitalsSchema = z
  .object({
    heart_rate_bpm: optNum(20, 300),
    bp_systolic: optNum(40, 300),
    bp_diastolic: optNum(20, 200),
    spo2_pct: optNum(50, 100),
    temperature_c: optNum(30, 45),
    weight_kg_at_exam: optNum(1, 400),
  })
  .superRefine((v, ctx) => {
    if (v.bp_systolic !== undefined && v.bp_diastolic !== undefined && v.bp_systolic <= v.bp_diastolic) {
      ctx.addIssue({ code: 'custom', path: ['bp_systolic'], message: 'bp' });
    }
  });
export type VitalsValues = z.output<typeof vitalsSchema>;

const TYPICAL: Record<string, [number, number]> = {
  heart_rate_bpm: [40, 140],
  bp_systolic: [90, 180],
  bp_diastolic: [50, 110],
  spo2_pct: [90, 100],
  temperature_c: [35, 39],
};

/** Values outside typical (but legal) ranges: shown as "please confirm", never blocking. */
export function vitalWarnings(v: Partial<Record<string, number | undefined>>): string[] {
  return Object.entries(TYPICAL)
    .filter(([k, [lo, hi]]) => v[k] !== undefined && (v[k]! < lo || v[k]! > hi))
    .map(([k]) => k);
}

// ------------------------------------------------------------------ audio pre-check + server quality
export const AUDIO_EXT = ['.wav', '.mp3', '.flac'] as const; // backend whitelist (doc 01 section 4)
export const IMAGE_EXT = ['.png', '.jpg', '.jpeg'] as const;

export type Quality = 'good' | 'low' | 'unusable';

/** Maps the server validation result of an uploaded recording to the UI quality level. */
export function evaluateQuality(r: Pick<Recording, 'snr_db' | 'quality_score' | 'validation_report'> & { status: string }, minSnr = 8): { level: Quality; reasons: string[] } {
  const reasons: string[] = [];
  const warnings = ((r.validation_report as { warnings?: unknown })?.warnings as unknown[] | undefined) ?? [];
  for (const w of warnings) reasons.push(typeof w === 'string' ? w : JSON.stringify(w));
  if (r.status === 'rejected') return { level: 'unusable', reasons: reasons.length ? reasons : ['rejected'] };
  if (r.snr_db != null && r.snr_db < minSnr / 2) return { level: 'unusable', reasons: [...reasons, 'snr'] };
  if ((r.snr_db != null && r.snr_db < minSnr) || (r.quality_score != null && r.quality_score < 0.5) || warnings.length) {
    return { level: 'low', reasons: r.snr_db != null && r.snr_db < minSnr ? [...reasons, 'snr'] : reasons };
  }
  return { level: 'good', reasons };
}

export function checkAudioDuration(sec: number, min = 5, max = 120): 'short' | 'long' | null {
  if (sec < min) return 'short';
  if (sec > max) return 'long';
  return null;
}

// ------------------------------------------------------------------ AI result helpers
/** No numeric risk score exists in the API: derive an "abnormality probability" from class probabilities. */
export function abnormalProbability(a: Pick<AnalysisResult, 'class_probs' | 'pcg_class' | 'confidence'> | null | undefined): number | null {
  if (!a) return null;
  const normal = a.class_probs?.normal;
  if (typeof normal === 'number') return Math.round((1 - normal) * 100);
  return a.pcg_class === 'normal' ? Math.round((1 - a.confidence) * 100) : Math.round(a.confidence * 100);
}

export interface FeatureRow {
  key: string;
  group: 'time' | 'amplitude' | 'spectrum' | 'murmur';
  value: number | string | null;
  unit?: string;
  range?: [number, number];
  abnormal: boolean;
}

/** Feature table rows with reference ranges (adult resting values; informational). */
export function featureRows(a: AnalysisResult): FeatureRow[] {
  const row = (key: string, group: FeatureRow['group'], value: number | null | undefined, unit?: string, range?: [number, number]): FeatureRow => ({
    key,
    group,
    value: value ?? null,
    unit,
    range,
    abnormal: value != null && !!range && (value < range[0] || value > range[1]),
  });
  return [
    row('heart_rate_bpm', 'time', a.heart_rate_bpm, 'bpm', [50, 100]),
    row('hr_variability_ms', 'time', a.hr_variability_ms, 'ms'),
    row('s1_count', 'time', a.s1_count),
    row('s2_count', 'time', a.s2_count),
    row('mean_s1_s2_ms', 'time', a.mean_s1_s2_ms, 'ms', [200, 400]),
    row('mean_s2_s1_ms', 'time', a.mean_s2_s1_ms, 'ms', [250, 700]),
    row('systole_ms', 'time', a.systole_ms, 'ms', [200, 400]),
    row('diastole_ms', 'time', a.diastole_ms, 'ms', [250, 700]),
    row('dominant_freq_hz', 'spectrum', a.dominant_freq_hz, 'Hz', [20, 200]),
    row('murmur_grade', 'murmur', a.murmur_grade, '/6', [0, 1]),
    { key: 'murmur_timing', group: 'murmur', value: a.murmur_timing, abnormal: a.murmur_timing !== 'none' },
    { key: 'murmur_shape', group: 'murmur', value: a.murmur_shape ?? null, abnormal: false },
  ];
}

// ------------------------------------------------------------------ drugs: blocking rules
export type InteractionLevel = 'minor' | 'moderate' | 'major' | 'contraindicated';
const RANK: Record<InteractionLevel, number> = { minor: 1, moderate: 2, major: 3, contraindicated: 4 };

export function itemInteractionLevel(item: Pick<PrescriptionItem, 'interaction_warnings'>): InteractionLevel | null {
  let best: InteractionLevel | null = null;
  for (const w of item.interaction_warnings ?? []) {
    const lvl = (w as { level?: string })?.level as InteractionLevel | undefined;
    if (lvl && RANK[lvl] && (!best || RANK[lvl] > RANK[best])) best = lvl;
  }
  return best;
}

/**
 * Safety rule (doc 03 3.15): items with an allergy conflict or a "contraindicated"/"major" interaction can only be
 * accepted with a written reason that goes to the audit log. Pending safety checks block acceptance entirely.
 */
export function acceptRequirement(item: Pick<PrescriptionItem, 'allergy_warning' | 'safety_pending' | 'interaction_warnings'>): 'blocked' | 'reason' | 'free' {
  if (item.safety_pending) return 'blocked';
  const lvl = itemInteractionLevel(item);
  if (item.allergy_warning || lvl === 'contraindicated' || lvl === 'major') return 'reason';
  return 'free';
}

// ------------------------------------------------------------------ conclusion validation
export interface ConclusionDraft {
  diagnosis_text: string;
  recommendations: string;
  icd10_codes: string[];
  agreement_with_ai: 'agree' | 'partial' | 'disagree';
  disagreement_reason?: string | null;
  follow_up_date?: string | null;
}

export type SignBlocker = 'diagnosis_short' | 'no_icd' | 'recommendations' | 'reason' | 'pending_items' | 'followup_past' | 'no_ai';

/** Pre-sign checks mirroring doc 03 3.15 + backend sign rules (the server stays authoritative). */
export function signBlockers(d: ConclusionDraft, items: Pick<PrescriptionItem, 'status'>[], hasAi: boolean, todayIso: string): SignBlocker[] {
  const out: SignBlocker[] = [];
  if (!hasAi) out.push('no_ai');
  if (d.diagnosis_text.trim().length < 20) out.push('diagnosis_short');
  if (d.icd10_codes.length < 1) out.push('no_icd');
  if (!d.recommendations.trim()) out.push('recommendations');
  if (d.agreement_with_ai !== 'agree' && !(d.disagreement_reason ?? '').trim()) out.push('reason');
  if (items.some((i) => i.status === 'suggested' || i.status === 'draft')) out.push('pending_items');
  if (d.follow_up_date && d.follow_up_date <= todayIso) out.push('followup_past');
  return out;
}

export function conclusionLocked(c: Pick<Conclusion, 'status'> | null | undefined, status: ExamStatus): boolean {
  return status === 'completed' || c?.status === 'signed' || c?.status === 'amended';
}

/** Agreement level derived from the doctor's final class vs AI top-1 (shown as a hint, doctor can override). */
export function suggestAgreement(aiClass: string, finalClass: string): 'agree' | 'disagree' {
  return aiClass === finalClass ? 'agree' : 'disagree';
}

export const PROGRESS_STAGES = ['queued', 'validating', 'preprocessing', 'segmenting', 'features', 'classifying', 'spectrogram', 'llm_report', 'finalizing'] as const;
export type ProgressStage = (typeof PROGRESS_STAGES)[number];

export function stageIndex(stage: string | undefined): number {
  const i = PROGRESS_STAGES.indexOf(stage as ProgressStage);
  return i < 0 ? 0 : i;
}
