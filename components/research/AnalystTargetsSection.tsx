import { researchRequest } from '@/lib/research/client';
import type { components } from '@/lib/research/openapi.generated';
import { formatMarketDate, formatPercent, formatPrice, formatUserDateTime } from '@/lib/format';

type AnalystTargets = components['schemas']['AnalystTargets'];

/**
 * Precios objetivo por analista (firma, objetivo, fecha, recorrido). Fuente
 * gratuita y no oficial (Yahoo Finance): cada fila lleva fuente y fecha, la
 * cabecera la hora de obtención. Sin datos o con fallo se dice, nunca se
 * rellena. Nunca rechaza: un fallo de la fuente no rompe la ficha.
 */
export async function AnalystTargetsSection({ symbol, currency }: { symbol: string; currency?: string | null }) {
    let data: AnalystTargets | null = null;
    try {
        data = await researchRequest<AnalystTargets>(`/api/companies/${encodeURIComponent(symbol)}/analyst-targets`, { timeoutMs: 14000 });
    } catch {
        data = null;
    }
    const cur = currency || 'USD';
    return (
        <section aria-labelledby="analyst-targets-title" className="rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="analyst-targets">
            <h2 className="text-base font-semibold text-gray-100" id="analyst-targets-title">Precios objetivo de analistas</h2>
            {!data || data.status === 'unavailable' ? (
                <p className="mt-2 text-sm text-gray-400" role="status">{data?.note ?? 'No se pudieron consultar los precios objetivo ahora. Reintenta en unos minutos.'}</p>
            ) : data.status === 'empty' || data.rows.length === 0 ? (
                <p className="mt-2 text-sm text-gray-400" role="status">{data.note ?? 'Sin precios objetivo por analista para este valor.'}</p>
            ) : (
                <>
                    {data.consensus ? (
                        <p className="mt-1 text-sm text-gray-300">
                            Consenso: mediana {formatPrice(data.consensus.median, cur)} · media {formatPrice(data.consensus.mean, cur)} · rango {formatPrice(data.consensus.low, cur)} a {formatPrice(data.consensus.high, cur)}
                        </p>
                    ) : null}
                    <div className="mt-3 overflow-x-auto">
                        <table className="w-full min-w-[34rem] text-left text-sm">
                            <caption className="sr-only">Último precio objetivo por firma, de los últimos 12 meses</caption>
                            <thead className="text-xs text-gray-500">
                                <tr>
                                    <th className="py-1.5 pr-3 font-medium" scope="col">Firma</th>
                                    <th className="py-1.5 pr-3 font-medium" scope="col">Recomendación</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col">Objetivo</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col">Anterior</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col">Recorrido</th>
                                    <th className="py-1.5 font-medium" scope="col">Fecha</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {data.rows.map((row) => (
                                    <tr key={`${row.firm}-${row.date}`}>
                                        <th className="py-1.5 pr-3 font-medium text-gray-100" scope="row">{row.firm}</th>
                                        <td className="py-1.5 pr-3 text-gray-300">{row.rating ?? 'N/D'}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-100">{formatPrice(row.price_target, cur)}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-400">{row.prior_target ? formatPrice(row.prior_target, cur) : 'N/D'}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-300">{row.upside_percent === null || row.upside_percent === undefined ? 'N/D' : formatPercent(row.upside_percent, { fromRatio: false, signDisplay: 'always' })}</td>
                                        <td className="py-1.5 text-gray-400">{formatMarketDate(row.date)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    <p className="mt-2 text-xs text-gray-500">
                        Fuente: {data.source}
                        {data.source_url ? <> · <a className="text-teal-300" href={data.source_url} rel="noreferrer noopener" target="_blank">ver en Yahoo Finance</a></> : null}
                        {' '}· obtenido el {formatUserDateTime(data.fetched_at * 1000)}
                        {data.reference_price ? ` · recorrido frente a ${formatPrice(data.reference_price, cur)} (${data.reference_price_source ?? 'precio de referencia'})` : ' · sin precio de referencia: recorrido N/D'}
                        . Terceros, no verificado por GerarAI.
                    </p>
                </>
            )}
        </section>
    );
}
