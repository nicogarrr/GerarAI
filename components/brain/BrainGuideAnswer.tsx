import { useId } from 'react';
import { ExternalLink } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { safeAssistantSourceUrl, type AssistantCitationKind, type AssistantResponse, type AssistantSectionKey } from '@/lib/research/assistant-contract';
import { t } from '@/lib/i18n/t';

const SECTION_LABELS: Record<AssistantSectionKey, string> = {
    facts: 'Hechos', calculations: 'Cálculos', hypotheses: 'Hipótesis', inferences: 'Inferencias',
    contradictions: 'Contradicciones', insufficient_data: 'Datos insuficientes', conclusion: 'Conclusión',
};
const CITATION_LABELS: Record<AssistantCitationKind, string> = {
    news_event: 'Noticia atribuida', financial_fact: 'Dato financiero', document_chunk: 'Documento',
    claim_evidence: 'Evidencia de afirmación', market_observation: 'Observación de mercado', thesis_record: 'Tesis guardada',
};

/**
 * Copy de una respuesta o sección VACÍA.
 *
 * El contrato permite `answer: ''` y `body: ''`: no es un dato que falte, es
 * texto que el asistente no escribió, y un «Sin datos» a secas no dice si falta
 * la respuesta, si la evidencia no daba para una o si el modelo se quedó mudo.
 * Se nombra el caso y se dice dónde está la información que sí hay.
 */
function emptyAnswerCopy(status: 'answered' | 'insufficient_data'): string {
    return status === 'insufficient_data'
        ? 'El asistente no ha escrito una conclusión: la evidencia disponible no permite confirmar una conclusión. Revisa «Datos que faltan» más abajo para ver si se indica qué falta.'
        : 'El asistente ha devuelto la respuesta sin texto: no hay nada que mostrar como respuesta. Revisa las secciones y las fuentes disponibles más abajo.';
}

function emptySectionCopy(status: 'answered' | 'insufficient_data'): string {
    return status === 'insufficient_data'
        ? 'Esta sección no contiene texto. La respuesta está marcada como «Datos insuficientes», pero no indica el motivo de este apartado vacío.'
        : 'Sección sin cuerpo: el asistente la ha enviado vacía. Sin texto no hay nada que leer.';
}

function GuideCitation({ citation, index, id }: { citation: AssistantResponse['citations'][number]; index: number; id: string }) {
    const url = safeAssistantSourceUrl(citation.url);
    return (
        <li id={id} className="min-w-0 scroll-mt-3 rounded-lg border border-slate-700/60 bg-slate-900/60 p-2 text-xs text-slate-400">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-slate-200">Fuente {index + 1}</span>
                <Badge variant="outline">{CITATION_LABELS[citation.kind] ?? 'Fuente sin clasificar'}</Badge>
                {url
                    ? <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-w-0 items-center gap-1 text-indigo-300 underline underline-offset-2 hover:text-indigo-200"><span className="min-w-0 break-words">{citation.source || 'Fuente sin nombre'}</span><ExternalLink aria-hidden className="h-3 w-3 shrink-0" /></a>
                    : <span className="min-w-0 break-all text-slate-200">{citation.source || 'Fuente sin nombre'}</span>}
            </div>
            <div className="mt-1 break-all">Fecha de referencia: {citation.as_of || t('signals.noDate')}</div>
            {citation.excerpt
                ? <details className="mt-1"><summary className="cursor-pointer text-slate-500 hover:text-slate-300">Extracto original</summary><p className="mt-1 whitespace-pre-wrap break-words text-slate-300">{citation.excerpt}</p></details>
                : null}
        </li>
    );
}

/**
 * Respuesta del modo guía del Cerebro (asistente de research, POST
 * /api/research/assistant): secciones, citas tipadas y solo lectura. Sin
 * directiva 'use client': es presentacional y viaja en el paquete del
 * cliente por herencia de GlobalBrain.
 */
export function BrainGuideAnswer({ result }: { result: AssistantResponse }) {
    const sourcePrefix = useId();
    return (
        <div className="space-y-3">
            <p className="text-xs text-slate-500">Guía de {result.mode === 'guide' ? 'empresa' : 'exploración'} · Sin escritura: solo lectura, no modifica nada.</p>
            {result.status === 'insufficient_data' ? (
                <div role="status" className="rounded-lg border border-amber-800 bg-amber-950/20 p-3 text-sm text-amber-200">
                    <strong>Datos insuficientes</strong>
                    <p className="mt-1">La evidencia disponible no permite una conclusión confirmada.</p>
                </div>
            ) : null}
            <p className="whitespace-pre-wrap break-words">{result.answer?.trim() ? result.answer : emptyAnswerCopy(result.status)}</p>
            {result.sections.length ? (
                <div className="space-y-2">
                    {result.sections.map((section, index) => (
                        <details key={`${section.key}-${index}`} className="rounded-lg border border-slate-700/60 bg-slate-900/60" open={section.key === 'conclusion' && result.status === 'answered'}>
                            <summary className="min-h-11 cursor-pointer px-3 py-2 text-sm font-semibold text-slate-200">{SECTION_LABELS[section.key] ?? 'Sección sin clasificar'}</summary>
                            <div className="border-t border-slate-800 px-3 py-2">
                                <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-300">{section.body?.trim() ? section.body : emptySectionCopy(result.status)}</p>
                                {section.citation_ids.length ? (
                                    <ul aria-label="Fuentes de esta sección" className="mt-2 space-y-1 text-xs">
                                        {[...new Set(section.citation_ids)].map((citationId) => {
                                            const sourceIndex = result.citations.findIndex((citation) => citation.id === citationId);
                                            return (
                                                <li key={citationId}>
                                                    {sourceIndex >= 0 ? (
                                                        <a href={`#${sourcePrefix}-source-${sourceIndex}`} className="break-words text-indigo-300 underline underline-offset-2">
                                                            Fuente {sourceIndex + 1}: {result.citations[sourceIndex].source || 'Fuente sin nombre'}
                                                        </a>
                                                    ) : <span className="text-amber-200">Referencia sin fuente disponible: no se puede comprobar esta cita.</span>}
                                                </li>
                                            );
                                        })}
                                    </ul>
                                ) : <p className="mt-1 text-xs text-slate-500">Sin citas para esta sección: comprueba sus afirmaciones antes de usarlas.</p>}
                            </div>
                        </details>
                    ))}
                </div>
            ) : null}
            {result.missing_data.length || result.status === 'insufficient_data' ? (
                <div className="rounded-lg border border-amber-800/60 p-3">
                    <h4 className="text-sm font-semibold text-amber-200">Datos que faltan</h4>
                    {result.missing_data.length
                        ? <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-300">{result.missing_data.map((item, index) => <li key={index}>{item}</li>)}</ul>
                        : <p className="mt-1 text-sm text-slate-400">El asistente no ha indicado qué información falta. Puedes preguntar por el dato y el periodo que necesitas comprobar.</p>}
                </div>
            ) : null}
            {result.suggested_next_steps.length ? (
                <div>
                    <h4 className="text-sm font-semibold text-slate-200">Próximos pasos sugeridos</h4>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-400">{result.suggested_next_steps.map((item, index) => <li key={index}>{item}</li>)}</ul>
                </div>
            ) : null}
            <div className="border-t border-slate-800 pt-2">
                <h4 className="text-sm font-semibold text-slate-200">Citas y fuentes ({result.citations.length})</h4>
                {result.citations.length
                    ? <ul className="mt-2 grid min-w-0 gap-2">{result.citations.map((citation, index) => <GuideCitation key={`${citation.id}-${index}`} citation={citation} index={index} id={`${sourcePrefix}-source-${index}`} />)}</ul>
                    : <p className="mt-1 text-sm text-slate-500">El asistente no ha adjuntado fuentes. No puedes comprobar esta respuesta desde aquí.</p>}
            </div>
        </div>
    );
}
