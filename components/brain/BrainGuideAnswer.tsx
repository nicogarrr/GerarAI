'use client';

import { useId } from 'react';
import { ExternalLink } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { safeAssistantSourceUrl, type AssistantResponse } from '@/lib/research/assistant-contract';
import { t as legacyT } from '@/lib/i18n/t';
import { useT } from '@/lib/i18n/client';

const SECTION_KEYS = {
    facts: 'brain.guide.sections.facts', calculations: 'brain.guide.sections.calculations',
    hypotheses: 'brain.guide.sections.hypotheses', inferences: 'brain.guide.sections.inferences',
    contradictions: 'brain.guide.sections.contradictions', insufficient_data: 'brain.guide.sections.insufficientData',
    conclusion: 'brain.guide.sections.conclusion',
} as const;
const CITATION_KEYS = {
    news_event: 'brain.guide.citations.newsEvent', financial_fact: 'brain.guide.citations.financialFact',
    document_chunk: 'brain.guide.citations.documentChunk', claim_evidence: 'brain.guide.citations.claimEvidence',
    market_observation: 'brain.guide.citations.marketObservation', thesis_record: 'brain.guide.citations.thesisRecord',
} as const;

/**
 * Copy de una respuesta o sección VACÍA.
 *
 * El contrato permite `answer: ''` y `body: ''`: no es un dato que falte, es
 * texto que el asistente no escribió, y un «Sin datos» a secas no dice si falta
 * la respuesta, si la evidencia no daba para una o si el modelo se quedó mudo.
 * Se nombra el caso y se dice dónde está la información que sí hay.
 */
function emptyAnswerCopy(t: ReturnType<typeof useT>, status: 'answered' | 'insufficient_data'): string {
    return status === 'insufficient_data' ? t('brain.guide.emptyAnswerInsufficient') : t('brain.guide.emptyAnswer');
}

function emptySectionCopy(t: ReturnType<typeof useT>, status: 'answered' | 'insufficient_data'): string {
    return status === 'insufficient_data' ? t('brain.guide.emptySectionInsufficient') : t('brain.guide.emptySection');
}

function GuideCitation({ citation, index, id }: { citation: AssistantResponse['citations'][number]; index: number; id: string }) {
    const t = useT();
    const url = safeAssistantSourceUrl(citation.url);
    return (
        <li id={id} className="min-w-0 scroll-mt-3 rounded-lg border border-slate-700/60 bg-slate-900/60 p-2 text-xs text-slate-400">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-slate-200">{t('brain.guide.sourceN', { n: index + 1 })}</span>
                <Badge variant="outline">{t(CITATION_KEYS[citation.kind] ?? 'brain.guide.citations.unclassified')}</Badge>
                {url
                    ? <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-w-0 items-center gap-1 text-indigo-300 underline underline-offset-2 hover:text-indigo-200"><span className="min-w-0 break-words">{citation.source || t('brain.guide.unnamedSource')}</span><ExternalLink aria-hidden className="h-3 w-3 shrink-0" /></a>
                    : <span className="min-w-0 break-all text-slate-200">{citation.source || t('brain.guide.unnamedSource')}</span>}
            </div>
            <div className="mt-1 break-all">{t('brain.guide.referenceDate', { date: citation.as_of || legacyT('signals.noDate') })}</div>
            {citation.excerpt
                ? <details className="mt-1"><summary className="cursor-pointer text-slate-400 hover:text-slate-200">{t('brain.guide.originalExcerpt')}</summary><p className="mt-1 whitespace-pre-wrap break-words text-slate-300">{citation.excerpt}</p></details>
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
    const t = useT();
    const sourcePrefix = useId();
    return (
        <div className="space-y-3">
            <p className="text-xs text-slate-400">{t('brain.guide.header', { kind: result.mode === 'guide' ? t('brain.guide.kindCompany') : t('brain.guide.kindExploration') })}</p>
            {result.status === 'insufficient_data' ? (
                <div role="status" className="rounded-lg border border-amber-800 bg-amber-950/20 p-3 text-sm text-amber-200">
                    <strong>{t('brain.guide.insufficientTitle')}</strong>
                    <p className="mt-1">{t('brain.guide.insufficientBody')}</p>
                </div>
            ) : null}
            <p className="whitespace-pre-wrap break-words">{result.answer?.trim() ? result.answer : emptyAnswerCopy(t, result.status)}</p>
            {result.sections.length ? (
                <div className="space-y-2">
                    {result.sections.map((section, index) => (
                        <details key={`${section.key}-${index}`} className="rounded-lg border border-slate-700/60 bg-slate-900/60" open={section.key === 'conclusion' && result.status === 'answered'}>
                            <summary className="min-h-11 cursor-pointer px-3 py-2 text-sm font-semibold text-slate-200">{t(SECTION_KEYS[section.key] ?? 'brain.guide.sections.unclassified')}</summary>
                            <div className="border-t border-slate-800 px-3 py-2">
                                <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-300">{section.body?.trim() ? section.body : emptySectionCopy(t, result.status)}</p>
                                {section.citation_ids.length ? (
                                    <ul aria-label={t('brain.guide.sectionSourcesAria')} className="mt-2 space-y-1 text-xs">
                                        {[...new Set(section.citation_ids)].map((citationId) => {
                                            const sourceIndex = result.citations.findIndex((citation) => citation.id === citationId);
                                            return (
                                                <li key={citationId}>
                                                    {sourceIndex >= 0 ? (
                                                        <a href={`#${sourcePrefix}-source-${sourceIndex}`} className="break-words text-indigo-300 underline underline-offset-2">
                                                            {t('brain.guide.sourceRef', { n: sourceIndex + 1, name: result.citations[sourceIndex].source || t('brain.guide.unnamedSource') })}
                                                        </a>
                                                    ) : <span className="text-amber-200">{t('brain.guide.missingRef')}</span>}
                                                </li>
                                            );
                                        })}
                                    </ul>
                                ) : <p className="mt-1 text-xs text-slate-400">{t('brain.guide.noCitations')}</p>}
                            </div>
                        </details>
                    ))}
                </div>
            ) : null}
            {result.missing_data.length || result.status === 'insufficient_data' ? (
                <div className="rounded-lg border border-amber-800/60 p-3">
                    <h4 className="text-sm font-semibold text-amber-200">{t('brain.guide.missingTitle')}</h4>
                    {result.missing_data.length
                        ? <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-300">{result.missing_data.map((item, index) => <li key={index}>{item}</li>)}</ul>
                        : <p className="mt-1 text-sm text-slate-400">{t('brain.guide.missingEmpty')}</p>}
                </div>
            ) : null}
            {result.suggested_next_steps.length ? (
                <div>
                    <h4 className="text-sm font-semibold text-slate-200">{t('brain.guide.nextSteps')}</h4>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-400">{result.suggested_next_steps.map((item, index) => <li key={index}>{item}</li>)}</ul>
                </div>
            ) : null}
            <div className="border-t border-slate-800 pt-2">
                <h4 className="text-sm font-semibold text-slate-200">{t('brain.guide.citationsTitle', { n: result.citations.length })}</h4>
                {result.citations.length
                    ? <ul className="mt-2 grid min-w-0 gap-2">{result.citations.map((citation, index) => <GuideCitation key={`${citation.id}-${index}`} citation={citation} index={index} id={`${sourcePrefix}-source-${index}`} />)}</ul>
                    : <p className="mt-1 text-sm text-slate-400">{t('brain.guide.noSources')}</p>}
            </div>
        </div>
    );
}
