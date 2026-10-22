import {
    getSourceCoverage,
    type SourceCoverageCompany,
    type SourceCoverageHistoryItem,
    type SourceCoverageReport,
    type SourceCoverageState,
} from '@/lib/actions/source-coverage.actions';

const STATE_LABEL: Record<SourceCoverageState, string> = {
    fuente_obtenida: 'Fuente obtenida',
    abstencion_en_chequeo: 'Sin datos nuevos',
    ultimo_chequeo_con_error: 'Último chequeo con error',
    nunca_chequeado: 'Nunca chequeado',
    sin_chequeo_posible: 'Sin chequeo posible',
    sin_ejecuciones_aun: 'Aún sin chequeos',
    estado_del_almacen_no_fiable: 'Registro no fiable',
    estado_fuera_retencion: 'Estado desconocido (fuera de retención)',
};

const STATE_TONE: Record<SourceCoverageState, string> = {
    fuente_obtenida: 'text-emerald-400',
    abstencion_en_chequeo: 'text-gray-400',
    ultimo_chequeo_con_error: 'text-red-400',
    nunca_chequeado: 'text-amber-300',
    sin_chequeo_posible: 'text-gray-500',
    sin_ejecuciones_aun: 'text-gray-500',
    estado_del_almacen_no_fiable: 'text-red-400',
    estado_fuera_retencion: 'text-gray-500',
};

const PENDING_LABEL: Record<string, string> = {
    resolver_fuente_oficial_de_transcripcion: 'Sin fuente oficial de transcripción',
    sin_activo_de_transcripcion_verificado: 'Sin transcripción verificada',
    leer_fecha_de_llamada_del_documento: 'Falta fecha de llamada en el documento',
    sin_comunicado_financiero_registrado: 'Sin comunicado financiero registrado',
};

const OUTCOME_LABEL: Record<string, string> = {
    extraido: 'fuente obtenida',
    abstencion: 'sin datos nuevos',
    error: 'error',
};

const KIND_LABEL: Record<string, string> = {
    transcript: 'transcripción',
    press_release: 'comunicado',
};

function outcomesSummary(outcomes: Record<string, number>): string {
    return Object.entries(outcomes)
        .map(([k, n]) => `${n} ${OUTCOME_LABEL[k] ?? k}`)
        .join(' · ');
}

function CompanyRow({ company }: { company: SourceCoverageCompany }) {
    const c = company;
    // Fuera de retención (evicción): el backend marca estado_fuera_retencion
    // porque pudo haberse chequeado; NUNCA afirmar "nunca" en ese caso.
    const stateLabel = STATE_LABEL[c.state];
    return (
        <li className="rounded-lg border border-gray-800 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-semibold text-gray-100">{c.ticker}</span>
                {c.in_portfolio ? <span className="rounded border border-gray-700 px-1.5 text-xs text-gray-400">Cartera</span> : null}
                {c.in_watchlist ? <span className="rounded border border-gray-700 px-1.5 text-xs text-gray-400">Watchlist</span> : null}
                <span className={`text-xs font-medium ${STATE_TONE[c.state]}`}>{stateLabel}</span>
            </div>
            <p className="mt-1 text-xs text-gray-400">
                {c.last_checked_on
                    ? `Último chequeo: ${c.last_checked_on}${c.from_history ? ' (recuperado del histórico)' : ''}`
                    : 'Sin fecha de chequeo registrada'}
                {c.state === 'ultimo_chequeo_con_error' && c.last_good_checked_on
                    ? ` · Último chequeo bueno: ${c.last_good_checked_on}`
                    : null}
            </p>
            {c.transcript_assets > 0 ? (
                <p className="mt-1 text-xs text-gray-500">
                    Documentos: {c.transcript_assets} ({c.transcript_assets_with_call_date} con fecha de llamada)
                </p>
            ) : null}
            {c.pending.length ? (
                <p className="mt-1 text-xs text-gray-500">
                    Pendiente: {c.pending.map((p) => PENDING_LABEL[p] ?? p).join(' · ')}
                </p>
            ) : null}
        </li>
    );
}

function HistoryList({ history }: { history: SourceCoverageHistoryItem[] }) {
    if (!history.length) return <p className="text-xs text-gray-500">Sin chequeos registrados todavía.</p>;
    return (
        <ul className="grid gap-2">
            {history.map((h, i) => (
                <li className="text-xs text-gray-400" key={`${h.url}-${h.checked_on}-${i}`}>
                    <span className="font-medium text-gray-300">{h.ticker}</span>
                    {' · '}{KIND_LABEL[h.kind] ?? h.kind}
                    {h.period ? ` (${h.period})` : ''}
                    {' · '}<span className={h.outcome === 'error' ? 'text-red-400' : ''}>{OUTCOME_LABEL[h.outcome] ?? h.outcome}</span>
                    {' · '}{h.checked_on}
                    {h.content_changed ? ' · contenido cambiado' : ''}
                </li>
            ))}
        </ul>
    );
}

function StoreBanners({ report }: { report: SourceCoverageReport }) {
    const { store, job_last_run: job } = report;
    return (
        <>
            {store.latest === 'corrupto' || store.latest === 'ilegible' ? (
                <p role="alert" className="rounded-lg border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
                    El registro de chequeos no es fiable ahora mismo ({store.latest}); las fechas mostradas pueden no estar completas.
                </p>
            ) : null}
            {store.incident?.status === 'activo_o_sin_sanar' ? (
                <p role="alert" className="rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-300">
                    Hay una incidencia activa en el registro de chequeos ({store.incident.file}).
                </p>
            ) : null}
            {store.incident?.status === 'historico_sanado' ? (
                <p className="text-xs text-gray-500">Incidencia histórica del registro, ya resuelta.</p>
            ) : null}
            {store.at_retention_cap ? (
                <p className="text-xs text-gray-500">
                    El registro alcanzó su límite de retención: algunos estados aparecen como desconocidos aunque pudieron chequearse.
                </p>
            ) : null}
            {job === null ? (
                <p className="text-xs text-gray-500">
                    No hay una ejecución del chequeo programado legible todavía (arranque normal o registro no legible).
                </p>
            ) : !job.finished ? (
                <p role="alert" className="rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-300">
                    La última ejecución programada ({job.day}) no terminó{job.error ? `: ${job.error}` : ''}.
                </p>
            ) : (
                <p className="text-xs text-gray-500">
                    Última ejecución programada: {job.day}
                    {Object.keys(job.outcomes).length ? ` (${outcomesSummary(job.outcomes)})` : ''}
                    {job.had_errors ? ' · con errores' : ''}. {job.note}
                </p>
            )}
        </>
    );
}

export function SourceCoverageView({ report }: { report: SourceCoverageReport }) {
    return (
        <section aria-labelledby="source-coverage-title" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
            <h2 className="font-semibold text-gray-100" id="source-coverage-title">Cobertura de fuentes</h2>
            <p className="mt-1 text-xs text-gray-500">
                Universo: tu cartera + tu watchlist ({report.universe_size} empresas), leído de tu cuenta.
            </p>
            <p className="mt-1 text-xs text-gray-400">{report.note}</p>
            <div className="mt-3 grid gap-2">
                <StoreBanners report={report} />
            </div>
            {report.companies.length ? (
                <ul className="mt-3 grid gap-3 sm:grid-cols-2">
                    {report.companies.map((c) => <CompanyRow company={c} key={c.ticker} />)}
                </ul>
            ) : (
                <p className="mt-3 text-xs text-gray-500">No hay empresas en el universo todavía.</p>
            )}
            <details className="mt-4">
                <summary className="cursor-pointer text-xs text-gray-400 underline">Chequeos recientes ({report.history.length})</summary>
                <div className="mt-2"><HistoryList history={report.history} /></div>
            </details>
        </section>
    );
}

export function SourceCoverageUnavailable() {
    // Un 404 o un corte de red NO es "sin fuentes": es cobertura no legible.
    return (
        <section aria-labelledby="source-coverage-title" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
            <h2 className="font-semibold text-gray-100" id="source-coverage-title">Cobertura de fuentes</h2>
            <p role="alert" className="mt-2 text-sm text-gray-400">
                No pudimos leer la cobertura de fuentes ahora mismo. Esto no significa que falten fuentes: el servicio no respondió.
            </p>
        </section>
    );
}

export default async function SourceCoverage() {
    const result = await getSourceCoverage();
    if (result.status === 'unavailable') return <SourceCoverageUnavailable />;
    return <SourceCoverageView report={result.report} />;
}
