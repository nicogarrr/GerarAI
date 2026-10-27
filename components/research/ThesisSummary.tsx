import { formatGeneratedDate } from '@/lib/format';
import { cleanThesisText } from '@/lib/research/thesis-text';

export type ThesisTextVersion = { status: string; version: number; created_at?: string | null; executive_summary?: string | null };

/** Publication alone does not establish that persisted valuation prose is usable. */
export function canShowThesisText(thesis: ThesisTextVersion, model: { publishable: boolean } | null | undefined): boolean {
  return (thesis.status === 'published' || thesis.status === 'approved') && model?.publishable === true;
}

export function WithheldThesisText({ thesis, model }: { thesis: ThesisTextVersion; model: { publishable: boolean } | null | undefined }) {
  const generated = formatGeneratedDate(thesis.created_at);
  return <p role="note" className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm leading-6 text-amber-200">
    Texto archivado de v{thesis.version}{generated ? `, generada el ${generated}` : ', sin fecha de generación verificada'}: resumen y cifras retenidos porque {thesis.status !== 'published' && thesis.status !== 'approved' ? 'la tesis no está publicada ni aprobada' : model?.publishable === false ? 'el modelo no es publicable' : 'no se pudo verificar que el modelo sea publicable'}. No se presentan como análisis actual; el original se conserva guardado.
  </p>;
}

export function ThesisSummary({ thesis, model }: { thesis: ThesisTextVersion; model: { publishable: boolean } | null | undefined }) {
  return canShowThesisText(thesis, model)
    ? <p className="mt-3 line-clamp-3 text-sm leading-6 text-gray-300 md:line-clamp-none">{cleanThesisText(thesis.executive_summary)}</p>
    : <WithheldThesisText thesis={thesis} model={model} />;
}
