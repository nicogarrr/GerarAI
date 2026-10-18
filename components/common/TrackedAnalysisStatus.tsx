import { analysisStatusLabel, type TrackedAnalysisStatus as Status } from '@/lib/tracked-analysis-status';
import { formatUserDateTime } from '@/lib/format';
export function TrackedAnalysisStatus({ analysis }: { analysis?: Status | null }) {
  const label = analysisStatusLabel(analysis);
  return label && analysis ? <span className="mt-1 block text-xs font-normal text-gray-500">{label} · {formatUserDateTime(analysis.as_of)}</span> : null;
}
