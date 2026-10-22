import {
    getSourceCoverage,
    type SourceCoverageCompany,
    type SourceCoverageHistoryItem,
    type SourceCoverageReport,
    type SourceCoverageState,
    type SourceCoverageTranscriptSource,
} from '@/lib/actions/source-coverage.actions';

/** Nota de usuario en español (la del backend es técnica: no se muestra tal cual). */
const COVERAGE_NOTE = 'Tener la transcripción no significa que el compromiso se haya cumplido.';
/** Sustituye a job.note del backend (técnica y sin acentos). */
const JOB_RUN_NOTE = 'Es la última ejecución programada; no indica la salud actual del chequeo.';

const STATE_LABEL: Record<SourceCoverageState, string> = {
    fuente_obtenida: 'Fuente obtenida',
    abstencion_en_chequeo: 'No se pudo obtener la fuente',
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
    abstencion: 'fuente no obtenida',
    error: 'error',
};

const ORIGIN_LABEL: Record<string, string> = {
    href_ir_leido: 'enlace leído de la página de relación con inversores',
    url_dominio_oficial_por_busqueda: 'URL en dominio oficial hallada por búsqueda; no enlazada en la página IR consultada',
};

const KIND_LABEL: Record<string, string> = {
    transcript: 'transcripción',
    press_release: 'comunicado',
};

const STATE_GROUP: Record<SourceCoverageState, { label: string; order: number }> = {
    fuente_obtenida: { label: 'con fuente obtenida', order: 0 },
    abstencion_en_chequeo: { label: 'sin fuente obtenida en el último chequeo', order: 1 },
    ultimo_chequeo_con_error: { label: 'con error en el último chequeo', order: 2 },
    nunca_chequeado: { label: 'nunca chequeadas', order: 3 },
    sin_chequeo_posible: { label: 'sin chequeo posible', order: 4 },
    sin_ejecuciones_aun: { label: 'aún sin chequeos', order: 5 },
    estado_fuera_retencion: { label: 'de estado desconocido', order: 6 },
    estado_del_almacen_no_fiable: { label: 'de estado desconocido', order: 6 },
};

/** Contadores honestos: cada estado cae en su grupo, nada se inventa. */
function CoverageSummary({ companies }: { companies: SourceCoverageCompany[] }) {
    const counts = new Map<string, { label: string; order: number; n: number }>();
    let pendingCount = 0;
    for (const c of companies) {
        const g = STATE_GROUP[c.state] ?? { label: 'de estado desconocido', order: 6 };
        const cur = counts.get(g.label) ?? { ...g, n: 0 };
        cur.n += 1;
        counts.set(g.label, cur);
        if (c.pending.length) pendingCount += 1;
    }
    const parts = [...counts.values()].sort((a, b) => a.order - b.order).map((g) => `${g.n} ${g.label}`);
    return (
        <p className="mt-2 text-xs text-gray-400">
            {parts.join(' · ')}
            {pendingCount ? ` · ${pendingCount} con tareas pendientes` : ''}
        </p>
    );
}

function safeUrl(url: string | null | undefined): string | null {
    // Solo URLs http(s) devueltas por el backend; nunca reconstruidas.
    return url && /^https?:\/\//.test(url) ? url : null;
}

function TranscriptSourceLine({ source: src }: { source: SourceCoverageTranscriptSource }) {
    const url = safeUrl(src.url);
    const dateSourceUrl = safeUrl(src.call_date_source !== 'documento' ? src.call_date_source : null);
    return (
        <li className="text-xs text-gray-400">
            {url ? <a className="underline" href={url} rel="noopener noreferrer" target="_blank">{src.label || 'Transcripción'}</a> : <span>{src.label || 'Transcripción'}</span>}
            {src.period ? ` (${src.period})` : ''}
            {' · '}{src.format === 'html' ? 'página del emisor' : 'PDF'}
            {' · '}{ORIGIN_LABEL[src.origin] ?? 'origen registrado'}
            {src.call_date
                ? dateSourceUrl
                    ? <> · <a className="underline" href={dateSourceUrl} rel="noopener noreferrer" target="_blank">Fecha según comunicado del IR</a>: {src.call_date}</>
                    : <> · Fecha de llamada: {src.call_date} (según el documento)</>
                : null}
        </li>
    );
}

function outcomesSummary(outcomes: Record<string, number>): string {
    return Object.entries(outcomes)
        .map(([k, n]) => `${n} ${OUTCOME_LABEL[k] ?? k}`)
        .join(' · ');
}

function CompanyRow({ company }: { company: SourceCoverageCompany }) {
    const c = company;
    // Fuera de retención (evicción): el backend marca estado_fuera_retencion
    // porque pudo haberse chequeado; NUNCA afirmar "nunca" en ese caso.
    const stateLabel = STATE_LABEL[c.state] ?? 'Estado desconocido';
    const stateTone = STATE_TONE[c.state] ?? 'text-gray-500';
    return (
        <li className="rounded-lg border border-gray-800 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-semibold text-gray-100">{c.ticker}</span>
                {c.in_portfolio ? <span className="rounded border border-gray-700 px-1.5 text-xs text-gray-400">Cartera</span> : null}
                {c.in_watchlist ? <span className="rounded border border-gray-700 px-1.5 text-xs text-gray-400">Watchlist</span> : null}
                <span className={`text-xs font-medium ${stateTone}`}>{stateLabel}</span>
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
            {c.transcript_sources.length + c.press_release_sources.length > 0 ? (
                <details className="mt-1">
                    <summary className="cursor-pointer text-xs text-gray-500 underline">Fuentes ({c.transcript_sources.length + c.press_release_sources.length})</summary>
                    <ul className="mt-1 grid gap-1">
                        {c.transcript_sources.map((src) => <TranscriptSourceLine key={src.url} source={src} />)}
                        {c.press_release_sources.map((prs) => (
                            <li className="text-xs text-gray-400" key={prs.url}>
                                {safeUrl(prs.url)
                                    ? <a className="underline" href={safeUrl(prs.url) ?? undefined} rel="noopener noreferrer" target="_blank">Comunicado financiero</a>
                                    : <span>Comunicado financiero</span>}
                                {prs.period ? ` (${prs.period})` : ''}
                            </li>
                        ))}
                    </ul>
                </details>
            ) : null}
            {c.transcript_origins.length ? (
                <p className="mt-1 text-xs text-gray-500">
                    Fuente de la transcripción: {c.transcript_origins.map((o) => ORIGIN_LABEL[o] ?? 'origen registrado').join(' · ')}
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
                    {safeUrl(h.url)
                        ? <> · <a className="underline" href={safeUrl(h.url) ?? undefined} rel="noopener noreferrer" target="_blank">fuente</a></>
                        : null}
                    {h.content_changed ? ' · cambió el documento/página' : ''}
                </li>
            ))}
        </ul>
    );
}

function StoreAlerts({ report }: { report: SourceCoverageReport }) {
    const store = report.store;
    const job = report.job_last_run;
    if (!store) {
        // Backend antiguo o respuesta incompleta: no se afirma cobertura.
        return (
            <p role="alert" className="rounded-lg border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
                La respuesta no incluyó el estado del registro de chequeos; las fechas mostradas pueden no estar completas.
            </p>
        );
    }
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
            {job !== null && !job.finished ? (
                <p role="alert" className="rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-300">
                    La última ejecución programada ({job.day}) no terminó{job.error ? `: ${job.error}` : ''}.
                </p>
            ) : null}
        </>
    );
}

function OperationalDetails({ report }: { report: SourceCoverageReport }) {
    const store = report.store;
    const job = report.job_last_run;
    if (!store) return null;
    return (
        <>
            {store.incident?.status === 'historico_sanado' ? (
                <p className="text-xs text-gray-500">Incidencia histórica del registro, ya resuelta.</p>
            ) : null}
            {store.at_retention_cap ? (
                <p className="text-xs text-gray-500">
                    El registro alcanzó su límite de conservación: algunos estados aparecen como desconocidos aunque pudieron chequearse.
                </p>
            ) : null}
            {job === null ? (
                <p className="text-xs text-gray-500">
                    No hay una ejecución del chequeo automático legible todavía (arranque normal o registro no legible).
                </p>
            ) : job.finished ? (
                <p className="text-xs text-gray-500">
                    Última ejecución programada: {job.day}
                    {Object.keys(job.outcomes).length ? ` (${outcomesSummary(job.outcomes)})` : ''}
                    {job.had_errors ? ' · con errores' : ''}. {JOB_RUN_NOTE}
                </p>
            ) : null}
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
            <p className="mt-1 text-xs text-gray-400">{COVERAGE_NOTE}</p>
            <div className="mt-3 grid gap-2">
                <StoreAlerts report={report} />
            </div>
            <CoverageSummary companies={report.companies} />
            {report.companies.length ? (
                <details className="mt-3">
                    <summary className="cursor-pointer text-xs text-gray-400 underline">Cobertura por empresa ({report.companies.length})</summary>
                    <ul className="mt-3 grid gap-3 sm:grid-cols-2">
                        {report.companies.map((c) => <CompanyRow company={c} key={c.ticker} />)}
                    </ul>
                </details>
            ) : (
                <p className="mt-3 text-xs text-gray-500">No hay empresas en el universo todavía.</p>
            )}
            <details className="mt-4">
                <summary className="cursor-pointer text-xs text-gray-400 underline">Detalle operativo y chequeos recientes ({report.history.length})</summary>
                <div className="mt-2 grid gap-2">
                    <OperationalDetails report={report} />
                    <HistoryList history={report.history} />
                </div>
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
