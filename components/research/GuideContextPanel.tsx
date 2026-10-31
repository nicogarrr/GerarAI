'use client';

import { Badge } from '@/components/ui/badge';
import { Panel } from '@/components/ui/panel';
import { safeAssistantSourceUrl, type GuideContext } from '@/lib/research/assistant-contract';
import { useT } from '@/lib/i18n/client';
import { formatUserDateTime } from '@/lib/format';

/**
 * Contexto de guía en la pestaña Seguir de la ficha: las revisiones abiertas
 * se anclan a una pregunta del Cerebro (modo guía, solo lectura) y las
 * noticias atribuidas se listan con su fecha y su provenance. Antes vivía en
 * el lateral de /research/assistant; la página se unificó en el Cerebro.
 */
export function GuideContextPanel({ ticker, context, hideReviews = false }: { ticker: string; context: GuideContext | null; hideReviews?: boolean }) {
    const t = useT();
    function askWithReview(reviewId: number) {
        window.dispatchEvent(new CustomEvent('gerarai:open-brain', { detail: { ticker, review_id: reviewId } }));
    }
    if (!context) {
        return (
            <Panel title="Guía de investigación">
                <p role="status" className="text-sm text-amber-200">No se pudo cargar el contexto de guía.</p>
            </Panel>
        );
    }
    return (
        <Panel title="Guía de investigación">
            <div className="space-y-5 text-sm">
                {hideReviews ? null : <div>
                    <h3 className="font-semibold text-gray-200">Revisiones abiertas</h3>
                    {context.open_reviews.length ? (
                        <ul className="mt-2 space-y-2">
                            {context.open_reviews.map((review) => (
                                <li key={review.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-800 p-2">
                                    <span className="min-w-0 flex-1 break-words text-gray-300">#{review.id} · {review.summary}</span>
                                    <button
                                        type="button"
                                        onClick={() => askWithReview(review.id)}
                                        className="min-h-11 rounded-lg border border-teal-700 px-3 text-teal-300 transition hover:border-teal-500 hover:text-teal-200"
                                    >
                                        Preguntar al Cerebro
                                    </button>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="mt-2 text-gray-500">Sin revisiones abiertas.</p>
                    )}
                </div>}
                <div>
                    <h3 className="font-semibold text-gray-200">Últimas noticias atribuidas</h3>
                    {context.latest_news.length ? (
                        <ul className="mt-2 space-y-2">
                            {context.latest_news.map((news) => (
                                <li key={news.id} className="rounded-lg border border-gray-800 p-2">
                                    <Badge variant="outline">Noticia atribuida</Badge>
                                    <p className="mt-1 break-words text-gray-300">{safeAssistantSourceUrl(news.source_url) ? <a href={safeAssistantSourceUrl(news.source_url)!} target="_blank" rel="noopener noreferrer" className="text-teal-300 underline">{news.title}</a> : news.title}</p>
                                    <p className="mt-1 text-xs text-gray-500">{news.source || 'Fuente sin datos'} · {news.date_source === 'gdelt_first_seen' ? 'Detectada' : news.date_source === 'ingested_at_fallback' ? 'Incorporada' : news.date_source === 'source' ? 'Publicada' : 'Fecha registrada'}: {news.date ? formatUserDateTime(news.date) : t('signals.noDate')}</p>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="mt-2 text-gray-500">Sin datos de noticias.</p>
                    )}
                </div>
                {context.missing_data.length ? (
                    <div>
                        <h3 className="font-semibold text-gray-200">Datos que faltan en el contexto</h3>
                        <ul className="mt-2 list-disc pl-5 text-gray-400">{context.missing_data.map((item, index) => <li key={index}>{item}</li>)}</ul>
                    </div>
                ) : null}
            </div>
        </Panel>
    );
}
