'use client';
import { useState } from 'react';
import { analystRatingEs } from '@/lib/research/analyst-rating-es';
import type { components } from '@/lib/research/openapi.generated';
import { formatMarketDate, formatNumber, formatPercent, formatPrice, formatUserDateTime } from '@/lib/format';
type AnalystTargets = components['schemas']['AnalystTargets'];
export function AnalystTargetsView({data,currency}:{data:AnalystTargets|null;currency?:string|null}) {
    // Only this response can declare the unit of its target prices. The
    // company master may use a different scale (e.g. GBP versus GBX).
    const [page, setPage] = useState(0);
    const count = data?.rows.length ?? 0;
    const pages = Math.max(1, Math.ceil(count / 5));
    const current = Math.min(page, pages - 1);
    const rows = data?.rows.slice(current * 5, (current + 1) * 5) ?? [];
    const cur = data?.currency?.trim() || null;
    const fmtTarget = (value: number | null | undefined) =>
        value === null || value === undefined
            ? 'N/D'
            : cur
              ? formatPrice(value, cur)
              : formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (
        <section aria-labelledby="analyst-targets-title" className="rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="analyst-targets">
            <h2 className="sr-only text-base font-semibold text-gray-100 md:not-sr-only" id="analyst-targets-title">Precios objetivo de analistas</h2>
            {!data || data.status === 'unavailable' ? (
                <p className="mt-2 text-sm text-gray-400" role="status">{data?.note ?? 'No se pudieron consultar los precios objetivo ahora. Reintenta en unos minutos.'}</p>
            ) : data.rows.length === 0 && !data.consensus ? (
                <p className="mt-2 text-sm text-gray-400" role="status">{data.note ?? 'Sin precios objetivo por analista para este valor.'}</p>
            ) : (
                <>
                    {!cur ? <p className="mt-2 text-xs text-gray-400">Divisa no declarada por Yahoo: importes sin unidad verificada y potencial N/D.</p> : null}
                    {cur && currency && cur.toUpperCase() !== currency.trim().toUpperCase() ? (
                        <p className="mt-2 text-xs text-gray-400" data-testid="analyst-targets-currency-note">
                            Objetivos {cur.toUpperCase() === 'USD' ? '(ADR, USD)' : `en ${cur.toUpperCase()}`}: la ficha cotiza en {currency.trim().toUpperCase()}.
                        </p>
                    ) : null}
                    {data.consensus ? (
                        <div className="mt-1 text-sm text-gray-300">
                            <p>
                                Consenso agregado de Yahoo: mediana {fmtTarget(data.consensus.median)} · media {fmtTarget(data.consensus.mean)} · rango {fmtTarget(data.consensus.low)} a {fmtTarget(data.consensus.high)}
                            </p>

                        </div>
                    ) : null}
                    {data.rows.length === 0 ? (
                        <p className="mt-2 text-sm text-gray-400" role="status">{data.note ?? 'Solo consenso agregado, sin detalle por firma.'}</p>
                    ) : null}
                    {data.rows.length > 0 ? (
                    <>
                    {pages > 1 ? <nav aria-label="Paginación de analistas" className="mt-3 flex items-center justify-between gap-2 text-xs text-gray-300">
                      <button type="button" className="min-h-11 px-2 disabled:opacity-40" disabled={current === 0} onClick={() => setPage(current - 1)}>Anterior</button>
                      <span aria-live="polite"><span className="whitespace-nowrap">Página {current + 1} de {pages}</span> · {count} firmas</span>
                      <button type="button" className="min-h-11 px-2 disabled:opacity-40" disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Siguiente</button>
                    </nav> : null}
                    <ul aria-label="Precios objetivo por firma" className="mt-1 divide-y divide-gray-800 sm:hidden">
                        {rows.map((row) => (
                            <li className="py-2 text-sm" key={`${row.firm}-${row.date}`}>
                                <div className="flex items-baseline justify-between gap-3">
                                    <span className="min-w-0 font-medium text-gray-100">{row.firm}</span>
                                    <span className="shrink-0 tabular-nums text-gray-100">{fmtTarget(row.price_target)}</span>
                                </div>
                                <div className="mt-0.5 flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-gray-400">
                                    <span>{analystRatingEs(row.rating) ?? 'N/D'} · {formatMarketDate(row.date)}</span>
                                    <span className="tabular-nums">Anterior {fmtTarget(row.prior_target)} · <span title="Diferencia porcentual entre el objetivo de la firma y el precio de referencia al obtener los datos; no es una rentabilidad garantizada.">Potencial</span> {!cur || row.upside_percent === null || row.upside_percent === undefined ? 'N/D' : formatPercent(row.upside_percent, { fromRatio: false, signDisplay: 'always' })}</span>
                                </div>
                            </li>
                        ))}
                    </ul>
                    <div className="mt-1 hidden overflow-x-auto sm:block">
                        <table className="w-full min-w-[34rem] text-left text-sm">
                            <caption className="sr-only">Último precio objetivo por firma, de los últimos 12 meses</caption>
                            <thead className="text-xs text-gray-500">
                                <tr>
                                    <th className="py-1.5 pr-3 font-medium" scope="col">Firma</th>
                                    <th className="py-1.5 pr-3 font-medium" scope="col">Recomendación</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col">Objetivo</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col">Anterior</th>
                                    <th className="py-1.5 pr-3 text-right font-medium" scope="col" title="Diferencia porcentual entre el objetivo de la firma y el precio de referencia al obtener los datos; no es una rentabilidad garantizada.">Potencial</th>
                                    <th className="py-1.5 font-medium" scope="col">Fecha</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {rows.map((row) => (
                                    <tr key={`${row.firm}-${row.date}`}>
                                        <th className="py-1.5 pr-3 font-medium text-gray-100" scope="row">{row.firm}</th>
                                        <td className="py-1.5 pr-3 text-gray-300">{analystRatingEs(row.rating) ?? 'N/D'}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-100">{fmtTarget(row.price_target)}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-400">{fmtTarget(row.prior_target)}</td>
                                        <td className="py-1.5 pr-3 text-right tabular-nums text-gray-300">{!cur || row.upside_percent === null || row.upside_percent === undefined ? 'N/D' : formatPercent(row.upside_percent, { fromRatio: false, signDisplay: 'always' })}</td>
                                        <td className="py-1.5 text-gray-400">{formatMarketDate(row.date)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    </>
                    ) : null}
                    <p className="mt-2 text-xs text-gray-500">
                        Obtenido el {formatUserDateTime(data.fetched_at * 1000)}
                        {cur && data.reference_price ? ` · potencial frente a ${fmtTarget(data.reference_price)} (${data.reference_price_source ?? 'precio de referencia'})` : ' · sin precio de referencia con unidad verificada: potencial N/D'}
                        . Terceros, no verificado por GerarAI.
                    </p>
                </>
            )}
        </section>
    );
}
