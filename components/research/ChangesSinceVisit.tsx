'use client';

import { useEffect, useState } from 'react';
import { formatDate } from '@/lib/format';
import { metricLabel } from '@/lib/research/metric-labels';
import { changeHeadlineCopy } from '@/lib/research/change-copy';
import { resolveVisitBaseline } from '@/lib/research/visit-baseline';

interface ChangesSince {
    since: string;
    documentos: { total: number; items: Array<{ titulo: string; tipo: string; url: string | null; fecha: string | null }> };
    hechos: { total: number; por_metrica: Array<{ metric: string; n: number }> };
    cambios_tesis: Array<{ resumen: string; direccion: string; requiere_revision: boolean; fecha: string; fuente_url?: string | null; fuente_nombre?: string | null; tambien_en?: Array<{ url: string | null; fuente: string | null; fecha?: string | null }> | null }>;
}

/** Banner "desde tu ultima visita": solo lo guardado despues de tu ultima entrada. */
export function ChangesSinceVisit({ ticker }: { ticker: string }) {
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
        <section aria-label="Cambios desde tu última visita" className="rounded-lg border border-teal-500/30 bg-teal-500/5 px-3 py-2 text-sm text-gray-300">
            <p className="font-medium text-teal-200">Desde tu última visita ({formatDate(data.since)})</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-gray-400">
                {data.documentos.total > 0 ? (
                    <li>
                        {data.documentos.total} documento{data.documentos.total === 1 ? '' : 's'} nuevo{data.documentos.total === 1 ? '' : 's'}:{' '}
                        {data.documentos.items.slice(0, 3).map((doc, index) => (
                            <span key={`${doc.titulo}-${index}`}>
                                {index > 0 ? ', ' : ''}
                                {doc.url && /^https:\/\//.test(doc.url) ? (
                                    <a href={doc.url} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">{doc.titulo}</a>
                                ) : doc.titulo}
                            </span>
                        ))}
                        {data.documentos.total > 3 ? ' y más' : ''}
                    </li>
                ) : null}
                {data.hechos.total > 0 ? (
                    <li>
                        {data.hechos.total} dato{data.hechos.total === 1 ? '' : 's'} financiero{data.hechos.total === 1 ? '' : 's'} nuevo{data.hechos.total === 1 ? '' : 's'}
                        {' '}({data.hechos.por_metrica.slice(0, 4).map((m) => `${metricLabel(m.metric)} ×${m.n}`).join(', ')})
                    </li>
                ) : null}
                {data.cambios_tesis.slice(0, 3).map((change, index) => (
                    <li key={`${change.fecha}-${index}`}>
                        Tesis: {changeHeadlineCopy(change.resumen).text}{change.requiere_revision ? ' (requiere revisión)' : ''}
                        {changeHeadlineCopy(change.resumen).note ? <p className="mt-1 text-xs text-amber-300">{changeHeadlineCopy(change.resumen).note}</p> : null}
                        {/* Procedencia: la fuente del evento y las URLs absorbidas al
                            agrupar la misma noticia en dos idiomas quedan revisables. */}
                        {change.fuente_url && /^https:\/\//.test(change.fuente_url) ? (
                            <>
                                {' · '}
                                <a href={change.fuente_url} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">
                                    {change.fuente_nombre || 'Fuente'}
                                </a>
                            </>
                        ) : null}
                        {change.tambien_en?.map((entry, entryIndex) => (
                            entry.url && /^https:\/\//.test(entry.url) ? (
                                <span key={`${entry.url}-${entryIndex}`}>
                                    {' · también en '}
                                    <a href={entry.url} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">
                                        {entry.fuente || 'otra fuente'}
                                    </a>
                                </span>
                            ) : null
                        ))}
                    </li>
                ))}
            </ul>
        </section>
    );
}
