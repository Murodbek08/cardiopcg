import { useParams } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { IconFileTypePdf, IconPrinter } from '@tabler/icons-react';
import { Alert, Button, ErrorState, PageHeader, SkeletonRows, downloadFile, errorMessage, formatDate, formatDateTime, toast, AiDisclaimerBadge } from '@/shared';
import type { AiReport } from '@/shared/api/types';
import { useAuthStore } from '@/shared/store/auth';
import { useExam } from '../api';

/** A4 printable report. Only approved data: draft drug items never appear (doc 03 3.16). */
export function ExamReportPage() {
  const { t } = useTranslation('exams');
  const { id } = useParams({ strict: false }) as { id: string };
  const user = useAuthStore((s) => s.user);
  const q = useExam(id);
  if (q.isLoading) return <SkeletonRows rows={8} />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const e = q.data;
  const signed = e.status === 'completed' && !!e.conclusion && e.conclusion.status !== 'draft';
  if (!signed) {
    return <div><PageHeader title={t('report.title')} /><Alert tone="info">{t('report.unapproved')}</Alert></div>;
  }
  const c = e.conclusion!;
  const approved = (e.prescription?.items ?? []).filter((i) => i.status === 'approved');
  const full = e.report && 'differential_diagnoses' in e.report ? (e.report as AiReport) : null;

  return (
    <div>
      <div className="no-print mb-4 flex justify-end gap-2">
        <Button variant="outline" onClick={() => window.print()}><IconPrinter size={18} aria-hidden /> {t('report.print')}</Button>
        <Button onClick={() => void downloadFile(`/examinations/${id}/export/pdf`, undefined, `${e.exam_no}.pdf`).catch((err) => toast.error(errorMessage(err, t as never)))}><IconFileTypePdf size={18} aria-hidden /> PDF</Button>
      </div>
      <article className="mx-auto max-w-[210mm] space-y-5 rounded-lg border border-border bg-white p-8 text-black shadow-card print:border-0 print:shadow-none">
        <header className="flex items-start justify-between border-b border-neutral-300 pb-3">
          <div><h1 className="text-h1 font-bold">CardioPCG AI</h1><p className="text-sm">{t('report.title')} {e.exam_no} (v{c.version})</p></div>
          <p className="text-sm">{formatDate(c.signed_at)}</p>
        </header>
        <section className="print-avoid-break grid grid-cols-2 gap-2 text-sm">
          <p><b>{t('columns.patient')}:</b> {e.patient.full_name} ({e.patient.age})</p><p><b>MRN:</b> {e.patient.mrn}</p>
          <p><b>{t('vitals.bp')}:</b> {e.bp_systolic && e.bp_diastolic ? `${e.bp_systolic}/${e.bp_diastolic}` : '-'}</p><p><b>{t('vitals.hr')}:</b> {e.heart_rate_bpm ?? '-'}</p>
          <p><b>SpO2:</b> {e.spo2_pct ?? '-'}</p><p><b>{t('columns.date')}:</b> {formatDateTime(e.examined_at)}</p>
        </section>
        {e.analysis && (
          <section className="print-avoid-break text-sm"><h2 className="mb-1 text-h3 font-semibold">{t('analysis')} <AiDisclaimerBadge compact /></h2>
            <p>{t(`clinical:pcg_class.${e.analysis.pcg_class}`)}, {t(`clinical:severity.${e.analysis.severity}`)}; HR {e.analysis.heart_rate_bpm ?? '-'}; {t('confidence')} {Math.round(e.analysis.confidence * 100)}%</p>
            {full && <p className="mt-1">{full.summary}</p>}
          </section>
        )}
        <section className="print-avoid-break text-sm"><h2 className="mb-1 text-h3 font-semibold">{t('conclusion.title')}</h2>
          <p>{c.diagnosis_text}</p>
          <p className="mt-1"><b>ICD-10:</b> {c.icd10_codes.join(', ') || '-'}</p>
          <p className="mt-1"><b>{t('conclusion.recommendations')}:</b> {c.recommendations}</p>
          {c.follow_up_date && <p><b>{t('conclusion.follow_up')}:</b> {formatDate(c.follow_up_date)}</p>}
        </section>
        {approved.length > 0 && (
          <section className="print-avoid-break text-sm"><h2 className="mb-1 text-h3 font-semibold">{t('report.approved_drugs')}</h2>
            <table className="w-full border-collapse text-left"><thead><tr className="border-b border-neutral-300"><th className="py-1">{t('drugs.name')}</th><th>{t('drugs.dose')}</th><th>{t('drugs.frequency')}</th><th>{t('drugs.duration')}</th></tr></thead>
              <tbody>{approved.map((i) => <tr key={i.id} className="border-b border-neutral-200"><td className="py-1">{i.drug_name}</td><td>{i.dose}</td><td>{i.frequency}</td><td>{i.duration_days ?? '-'}</td></tr>)}</tbody></table>
          </section>
        )}
        <footer className="border-t border-neutral-300 pt-3 text-xs">
          <p>{t('report.signed_by', { at: formatDateTime(c.signed_at) })} {user?.role === 'doctor' ? user.full_name : ''}</p>
          <p className="mt-1">{t('report.disclaimer')}</p>
          {c.signature_hash && <p className="font-mono">{c.signature_hash.slice(0, 16)}</p>}
        </footer>
      </article>
    </div>
  );
}
