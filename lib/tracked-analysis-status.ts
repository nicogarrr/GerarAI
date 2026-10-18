export type TrackedAnalysisStatus = { status: string; as_of: string; thesis_status?: string | null };
export function analysisStatusLabel(analysis: TrackedAnalysisStatus | null | undefined): string | null {
  if (!analysis) return null;
  if (['queued', 'running', 'retrying'].includes(analysis.status)) return 'Analizando';
  if (analysis.status === 'dispatch_failed') return 'Análisis pendiente de reintento';
  if (analysis.status === 'failed') return 'No se pudo completar el análisis';
  if (analysis.status === 'succeeded') return analysis.thesis_status === 'insufficient_data' ? 'Análisis: faltan datos' : 'Análisis completado';
  return 'Estado de análisis no disponible';
}
