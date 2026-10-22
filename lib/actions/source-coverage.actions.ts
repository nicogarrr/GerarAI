'use server';

import { normalizeResearchBody, researchIdentityHeaders } from '@/lib/auth/research-identity';
import { RESEARCH_TIMEOUTS, requestSignal } from '@/lib/research/client';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

/** Estados que puede devolver GET /api/portfolio/source-coverage. */
export type SourceCoverageState =
    | 'sin_chequeo_posible'
    | 'nunca_chequeado'
    | 'ultimo_chequeo_con_error'
    | 'fuente_obtenida'
    | 'abstencion_en_chequeo'
    | 'sin_ejecuciones_aun'
    | 'estado_del_almacen_no_fiable'
    | 'estado_fuera_retencion';

export type SourceCoverageCompany = {
    ticker: string;
    in_portfolio: boolean;
    in_watchlist: boolean;
    transcript_status: string;
    transcript_assets: number;
    transcript_assets_with_call_date: number;
    press_release_registered: boolean;
    checkable_by_job: boolean;
    pending: string[];
    state: SourceCoverageState;
    last_checked_on: string | null;
    last_good_checked_on: string | null;
    outcomes: string[];
    from_history: boolean;
    universe_static_snapshot: boolean;
};

export type SourceCoverageHistoryItem = {
    ticker: string;
    url: string;
    kind: 'transcript' | 'press_release' | string;
    period: string | null;
    checked_on: string;
    outcome: 'extraido' | 'abstencion' | 'error' | string;
    reason: string | null;
    content_sha256: string | null;
    provenance: unknown;
    independent: boolean;
    content_changed: boolean;
};

export type SourceCoverageStore = {
    latest: 'ok' | 'ausente' | 'corrupto' | 'ilegible';
    first_run: boolean;
    recovered_from_history: boolean;
    recovered_urls: number;
    history_readable: boolean;
    evicted_tickers?: string[];
    at_retention_cap?: boolean;
    incident: null | { file: string; status: 'activo_o_sin_sanar' | 'historico_sanado' };
};

export type SourceCoverageJobRun = {
    day: string;
    /** true = la ejecución terminó sin excepción; NO implica éxito de fuentes ni salud actual. */
    finished: boolean;
    error: string | null;
    outcomes: Record<string, number>;
    had_errors: boolean;
    note: string;
};

export type SourceCoverageReport = {
    universe_source: string;
    universe_size: number;
    note: string;
    store: SourceCoverageStore;
    /** null = nunca ejecutado o ilegible (NO garantiza 'nunca'); ok=false = fallo del chequeo programado. */
    job_last_run: SourceCoverageJobRun | null;
    companies: SourceCoverageCompany[];
    history: SourceCoverageHistoryItem[];
};

/** 'ok' con datos o 'unavailable': un 404/red NO es "sin cobertura". */
export type SourceCoverageResult =
    | { status: 'ok'; report: SourceCoverageReport }
    | { status: 'unavailable' };

export async function getSourceCoverage(): Promise<SourceCoverageResult> {
    const path = '/api/portfolio/source-coverage';
    try {
        const identity = await researchIdentityHeaders({ method: 'GET', path, body: null });
        const response = await fetch(`${BACKEND_URL}${path}`, {
            cache: 'no-store',
            signal: requestSignal(null, RESEARCH_TIMEOUTS.GLOBAL_MS),
            headers: identity,
        });
        if (!response.ok) return { status: 'unavailable' };
        return { status: 'ok', report: (await response.json()) as SourceCoverageReport };
    } catch {
        return { status: 'unavailable' };
    }
}

// normalizeResearchBody se referencia para mantener el patron de firma del
// cliente de research cuando el endpoint admita escritura en el futuro.
void normalizeResearchBody;
