import { analysisStatusLabel, type TrackedAnalysisStatus as Status } from '@/lib/tracked-analysis-status';
import { formatUserDateTime } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
export function TrackedAnalysisStatus({ analysis, locale = DEFAULT_LOCALE }: { analysis?: Status | null; locale?: Locale }) {
  const label = analysisStatusLabel(analysis, locale);
  return label && analysis ? <span className="mt-1 block text-xs font-normal text-gray-500">{label} · {formatUserDateTime(analysis.as_of, undefined, undefined, locale)}</span> : null;
}
