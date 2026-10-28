'use client';

import { useState } from 'react';
import type { HistoricalStressReport, StressWindow } from '@/types/historical-stress';
import { formatPercent, formatMarketDate, formatCountEs } from '@/lib/format';

const day = (value?: string | null) => value ? formatMarketDate(value) : 'Sin datos';

const REASON_TEXT: Record<string, string> = {
    history_gaps: 'Histórico con huecos',
    provider_error: 'El proveedor (Yahoo) no respondió: reintenta más tarde',
    no_safe_symbol: 'Sin símbolo seguro para este valor (bolsa o divisa no mapeadas)',
    currency_mismatch: 'Yahoo devolvió otra divisa distinta de la guardada: se descarta por no ser el mismo instrumento',
    currency_unverified: 'Yahoo no indicó la divisa: no se puede verificar el instrumento',
    incomplete_portfolio: 'Histórico o valoración incompletos',
};

function WindowCard({ window }: { window: StressWindow }) {
    return <article className="rounded-xl border border-gray-800 bg-surface-1 p-4">
        <h3 className="text-xl font-semibold text-gray-100">{window.year}</h3>
        {window.status === 'SIN_DATOS' ? <div className="mt-3 text-sm text-amber-300">
            <p>N/D</p><p className="mt-1 text-gray-400">{REASON_TEXT[window.reason ?? ''] ?? 'Histórico o valoración incompletos'}</p>
            {window.missing_tickers?.length ? <p className="mt-2 break-words">Sin histórico suficiente: {window.missing_tickers.join(', ')}</p> : null}
        </div> : <>
            <dl className="mt-3 space-y-3 text-sm">
                <div className="flex justify-between gap-2"><dt className="text-gray-400">Retorno del año</dt><dd>{formatPercent(window.return)}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-gray-400">Caída máxima</dt><dd className="text-red-300">{formatPercent(window.max_drawdown)}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-gray-400">Pico / mínimo</dt><dd className="text-right">{day(window.peak_date)}<br />{day(window.trough_date)}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-gray-400">Recuperación desde el pico</dt><dd className="text-right"><span className="whitespace-nowrap">{window.recovery_date ? `${window.recovery_days} días` : window.recovery_status === 'history_gaps' ? 'Sin verificar: huecos' : 'No recuperado'}</span><br /><span className="whitespace-nowrap">{window.recovery_date ? day(window.recovery_date) : `Hasta ${day(window.last_observation)}`}</span></dd></div>
            </dl>
            <p className="mt-4 border-t border-gray-800 pt-3 text-xs text-gray-500">{day(window.start_date)} a {day(window.end_date)} · {typeof window.observations === 'number' ? formatCountEs(window.observations, 'sesión', 'sesiones') : 'Sesiones no disponibles'}</p>
        </>}
    </article>;
}

export default function HistoricalStressView({ report }: { report: HistoricalStressReport }) {
    const [page, setPage] = useState(0);
    const size = 5;
    const pages = Math.ceil(report.companies.length / size);
    return <div className="space-y-6">
        {report.mode === 'portfolio' && <section aria-label="Escenario de cartera">
            <h2 className="mb-3 font-semibold text-gray-100">Cartera actual</h2>
            <p className="mb-4 text-sm text-gray-400">Pesos actuales de renta variable, comprar y mantener. Sin caja ni efecto divisa. No es tu rendimiento real.</p>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{report.portfolio.map(window => <WindowCard key={window.year} window={window} />)}</div>
        </section>}
        {report.companies.length === 0 && <p className="rounded-xl border border-gray-800 p-5 text-gray-400">Sin posiciones de renta variable. Busca una compañía.</p>}
        {report.companies.slice(page * size, (page + 1) * size).map(company => <section key={company.ticker} aria-label={company.ticker}>
            <h2 className="mb-3 font-semibold text-teal-300">{company.ticker}{company.weight !== null ? ` · ${formatPercent(company.weight)} de renta variable` : ''}</h2>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{company.windows.map(window => <WindowCard key={window.year} window={window} />)}</div>
            <p className="mt-2 text-xs text-gray-500">
                {company.source_url ? <a className="inline-flex min-h-11 min-w-11 items-center text-teal-300 underline" href={company.source_url} target="_blank" rel="noopener noreferrer">{company.source}</a> : company.source} · Cierre ajustado · {company.currency ?? 'Divisa sin datos'} · Consultado {day(company.fetched_at)}
                {company.weight_as_of ? ` · Peso al ${day(company.weight_as_of)}` : ''}
            </p>
        </section>)}
        {pages > 1 && <nav aria-label="Paginación de compañías" className="flex items-center justify-between gap-3 text-sm">
            <button className="min-h-11 min-w-11 rounded border border-gray-700 px-3 py-2 disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Anterior</button>
            <span>{page + 1} / {pages}</span>
            <button className="min-h-11 min-w-11 rounded border border-gray-700 px-3 py-2 disabled:opacity-40" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Siguiente</button>
        </nav>}
        <details className="rounded-xl border border-gray-800 p-4 text-sm text-gray-400"><summary className="min-h-11 cursor-pointer py-3">Método y límites</summary>
            <p className="mt-3">Ventanas: años naturales 2008, 2020 y 2022, desde el último cierre del año anterior. Caída máxima desde un pico previo de la ventana. Recuperación: primer cierre que alcanza ese pico; días naturales desde el pico. Precios ajustados por dividendos y splits.</p>
            <p className="mt-2">Yahoo Finance es un proveedor secundario, no una fuente oficial. Sin sustitutos para compañías que aún no cotizaban. No se excluyen posiciones sin histórico para fabricar un resultado de cartera. Los pesos actuales introducen sesgo de supervivencia; el escenario no predice la próxima crisis.</p>
        </details>
    </div>;
}
