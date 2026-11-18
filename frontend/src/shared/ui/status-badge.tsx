import { useTranslation } from 'react-i18next';
import {
  IconCircleCheck, IconClock, IconLoader2, IconAlertOctagon, IconBan, IconPencil, IconUpload, IconBrain, IconStethoscope,
} from '@tabler/icons-react';
import { Badge, type Tone } from './badge';
import type { ExamStatus, ExamPriority, Severity, UserStatus, PcgClass, JobStatus, InteractionLevel, DrugStatus } from '@/shared/api/types';

type Kind = 'exam' | 'priority' | 'severity' | 'user' | 'pcg' | 'job' | 'interaction' | 'drug';

interface Cfg {
  tone: Tone;
  icon?: Parameters<typeof Badge>[0]['icon'];
  ns: string;
  key: string;
}

const EXAM: Record<ExamStatus, Omit<Cfg, 'ns' | 'key'>> = {
  draft: { tone: 'neutral', icon: IconPencil },
  uploaded: { tone: 'info', icon: IconUpload },
  queued: { tone: 'info', icon: IconClock },
  processing: { tone: 'info', icon: IconLoader2 },
  ai_ready: { tone: 'warning', icon: IconStethoscope },
  in_review: { tone: 'brand', icon: IconBrain },
  completed: { tone: 'success', icon: IconCircleCheck },
  failed: { tone: 'danger', icon: IconAlertOctagon },
  cancelled: { tone: 'neutral', icon: IconBan },
};

const SEVERITY: Record<Severity, Tone> = { none: 'success', mild: 'success', moderate: 'warning', severe: 'high', critical: 'danger' };
const PRIORITY: Record<ExamPriority, Tone> = { routine: 'neutral', urgent: 'warning', emergency: 'danger' };
const USER: Record<UserStatus, Tone> = { active: 'success', suspended: 'danger', pending: 'warning' };
const PCG: Record<PcgClass, Tone> = { normal: 'success', murmur: 'warning', extra_heart_sound: 'high', artifact: 'neutral', undetermined: 'neutral' };
const JOB: Record<JobStatus, Tone> = { pending: 'info', running: 'info', succeeded: 'success', failed: 'danger', cancelled: 'neutral' };
const INTERACTION: Record<InteractionLevel, Tone> = { minor: 'info', moderate: 'warning', major: 'high', contraindicated: 'danger' };
const DRUG: Record<DrugStatus, Tone> = { draft: 'neutral', published: 'success', archived: 'warning' };

function resolve(kind: Kind, value: string): Cfg {
  switch (kind) {
    case 'exam':
      return { ...(EXAM[value as ExamStatus] ?? { tone: 'neutral' }), ns: 'exams', key: `status.${value}` };
    case 'priority':
      return { tone: PRIORITY[value as ExamPriority] ?? 'neutral', ns: 'exams', key: `priority.${value}` };
    case 'severity':
      return { tone: SEVERITY[value as Severity] ?? 'neutral', ns: 'clinical', key: `severity.${value}` };
    case 'user':
      return { tone: USER[value as UserStatus] ?? 'neutral', ns: 'admin', key: `users.status.${value}` };
    case 'pcg':
      return { tone: PCG[value as PcgClass] ?? 'neutral', ns: 'clinical', key: `pcg_class.${value}` };
    case 'job':
      return { tone: JOB[value as JobStatus] ?? 'neutral', ns: 'common', key: `job.${value}` };
    case 'interaction':
      return { tone: INTERACTION[value as InteractionLevel] ?? 'neutral', ns: 'clinical', key: `interaction.${value}` };
    case 'drug':
      return { tone: DRUG[value as DrugStatus] ?? 'neutral', ns: 'drugs', key: `status.${value}` };
  }
}

/** Single entry point for every status/severity pill (icon + text + colour). */
export function StatusBadge({ kind, value, className }: { kind: Kind; value: string | null | undefined; className?: string }) {
  const { t } = useTranslation();
  if (!value) return <span className="text-muted">-</span>;
  const cfg = resolve(kind, value);
  return (
    <Badge tone={cfg.tone} icon={cfg.icon} className={className}>
      {t(`${cfg.ns}:${cfg.key}`, { defaultValue: value })}
    </Badge>
  );
}
