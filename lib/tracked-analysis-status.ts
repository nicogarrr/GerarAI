export type TrackedAnalysisStatus = {
  status: string;
  as_of: string;
  thesis_status?: string | null;
  /** Inputs pendientes del último modelo fundamental (los rellena el backend); null = sin información. */
  missing_inputs?: string[] | null;
};

// Claves técnicas del modelo → motivo en palabras (nunca el snake_case crudo).
const MISSING_INPUT_LABELS: Record<string, string> = {
  revenue_history_two_periods: 'ingresos de dos ejercicios',
  normalized_fcf_margin: 'margen FCF',
  shares_diluted: 'acciones en circulación',
  no_revenue_reported: 'aún sin ingresos reportados',
  annual_revenue_missing: 'ingresos anuales',
  fiscal_year: 'cierre de ejercicio',
};

function missingReason(missing: string[] | null | undefined): string | null {
  if (!missing || missing.length === 0) return null;
  const labels = [...new Set(missing.map((key) => MISSING_INPUT_LABELS[key] ?? 'supuestos del modelo'))];
  const shown = labels.slice(0, 2);
  const extra = labels.length > 2 ? ` y ${labels.length - 2} más` : '';
  return `${shown.join(' y ')}${extra}`;
}

export function analysisStatusLabel(analysis: TrackedAnalysisStatus | null | undefined): string | null {
  if (!analysis) return null;
  if (['queued', 'running', 'retrying'].includes(analysis.status)) return 'Analizando';
  if (analysis.status === 'dispatch_failed') return 'Análisis pendiente de reintento';
  if (analysis.status === 'failed') return 'No se pudo completar el análisis';
  if (analysis.status === 'succeeded') {
    if (analysis.thesis_status === 'insufficient_data') {
      const reason = missingReason(analysis.missing_inputs);
      return reason ? `Análisis: faltan datos (${reason})` : 'Análisis: faltan datos';
    }
    return 'Análisis completado';
  }
  return 'Estado de análisis no disponible';
}
