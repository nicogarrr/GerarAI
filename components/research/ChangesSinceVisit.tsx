'use client';

import { useEffect, useState } from 'react';
import { useFormat, useLocale, useT } from '@/lib/i18n/client';
import { metricLabel } from '@/lib/research/metric-labels';
import { changeHeadlineCopy } from '@/lib/research/change-copy';
import { markVisitRead, resolveVisitBaseline } from '@/lib/research/visit-baseline';
import { metricChangeParts, type MetricChange } from '@/lib/research/metric-changes';

interface ChangesSince {
    since: string;
    documentos: { total: number; items: Array<{ titulo: string; tipo: string; url: string | null; fecha: string | null }> };
    hechos: { total: number; por_metrica: Array<{ metric: string; n: number }> };
    cambios_metricas?: MetricChange[];
    cambios_tesis: Array<{ resumen: string; direccion: string; requiere_revision: boolean; fecha: string; fuente_url?: string | null; fuente_nombre?: string | null; tambien_en?: Array<{ url: string | null; fuente: string | null; fecha?: string | null }> | null }>;
}

/** Banner "desde tu ultima visita": solo lo guardado despues de tu ultima entrada. */
export function ChangesSinceVisit({ ticker }: { ticker: string }) {
    const t = useT();
    const locale = useLocale();
    const { formatDate } = useFormat();
    const [data, setData] = useState<ChangesSince | null>(null);
    useEffect(() => {
        let disposed = false;
        let baseline: string | null = null;
        try {
            baseline = resolveVisitBaseline(window.localStorage, window.sessionStorage, ticker, new Date());
        } catch {
            return; // Almacenamiento bloqueado: sin referencia no se inventa un diff.
        }
        if (!baseline) return;
        const controller = new AbortController();
        fetch(`/api/companies/${encodeURIComponent(ticker)}/changes-since?since=${encodeURIComponent(baseline)}`, {
            cache: 'no-store', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
        })
            .then((response) => (response.ok ? (response.json() as Promise<ChangesSince>) : null))
            .then((value) => { if (!disposed) setData(value && value.since ? value : null); })
            .catch(() => { if (!disposed) setData(null); });
        return () => { disposed = true; controller.abort(); };
    }, [ticker]);

    if (!data) return null;
    const total = data.documentos.total + data.hechos.total + data.cambios_tesis.length;
    if (total === 0) return null;
    return (
        <section aria-label={t('research.changesSinceVisit.sectionLabel')} className="rounded-lg border border-teal-500/30 bg-teal-500/5 px-3 py-2 text-sm text-gray-300">
            <p className="font-medium text-teal-200">{t('research.changesSinceVisit.heading', { date: formatDate(data.since) })}</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-gray-400">
                {data.documentos.total > 0 ? (
                    <li>
                        {data.documentos.total === 1 ? t('research.changesSinceVisit.newDocuments_one', { count: 1 }) : t('research.changesSinceVisit.newDocuments_other', { count: data.documentos.total })}{' '}
                        {data.documentos.items.slice(0, 3).map((doc, index) => (
                            <span key={`${doc.titulo}-${index}`}>
                                {index > 0 ? ', ' : ''}
                                {doc.url && /^https:\/\//.test(doc.url) ? (
                                    <a href={doc.url} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">{doc.titulo}</a>
                                ) : doc.titulo}
                            </span>
                        ))}
                        {data.documentos.total > 3 ? t('research.changesSinceVisit.andMore') : ''}
                    </li>
                ) : null}
                {data.hechos.total > 0 ? (
                    <li>
                        {data.hechos.total === 1 ? t('research.changesSinceVisit.newFacts_one', { count: 1 }) : t('research.changesSinceVisit.newFacts_other', { count: data.hechos.total })}
                        {' '}({data.hechos.por_metrica.slice(0, 4).map((m) => `${metricLabel(m.metric, locale)} ×${m.n}`).join(', ')})
                    </li>
                ) : null}
                {data.cambios_tesis.slice(0, 3).map((change, index) => (
                    <li key={`${change.fecha}-${index}`}>
                        {t('research.changesSinceVisit.thesis', { text: changeHeadlineCopy(change.resumen, locale).text })}{change.requiere_revision ? t('research.changesSinceVisit.needsReview') : ''}
                        {changeHeadlineCopy(change.resumen, locale).note ? <p className="mt-1 text-xs text-amber-300">{changeHeadlineCopy(change.resumen, locale).note}</p> : null}
                    </li>
                ))}
            </ul>
            {data.cambios_metricas && data.cambios_metricas.length > 0 ? (
                <ul className="mt-2 space-y-1 text-xs" aria-label={t('research.changesSinceVisit.metricsLabel')}>
                    {data.cambios_metricas.map((change) => {
                        const parts = metricChangeParts(change, locale);
                        return (
                            <li key={change.metric}>
                                <span className="text-gray-400">{metricLabel(change.metric, locale)}:</span>{' '}
                                {parts.before ? <><s className="text-gray-500">{parts.before}</s> → </> : null}
                                <span className="font-semibold text-gray-100">{parts.after}</span>
                                <span className="text-gray-500"> · {parts.note}{change.fuente ? t('research.changesSinceVisit.source', { source: change.fuente }) : ''}</span>
                            </li>
                        );
                    })}
                </ul>
            ) : null}
            <button type="button" className="mt-2 min-h-9 text-xs text-teal-300 underline-offset-2 hover:underline" onClick={() => {
                try { markVisitRead(window.localStorage, window.sessionStorage, ticker, new Date()); } catch { /* almacenamiento bloqueado */ }
                setData(null);
            }}>{t('research.changesSinceVisit.markRead')}</button>
        </section>
    );
}
