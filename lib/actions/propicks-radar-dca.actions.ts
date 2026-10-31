'use server';

import { researchRequest } from '@/lib/research/client';

export interface RadarDcaChange {
    status: 'history_pending' | 'not_comparable' | 'not_newer' | 'compared';
    changed: boolean | null;
    from_level?: number;
    to_level?: number;
    since_price_date?: string;
}

export interface RadarDcaOpportunity {
    ticker: string;
    name: string | null;
    sector: string | null;
    currency: string | null;
    level: number | null;
    level_label: string | null;
    /** "confirmed" | "forming" (mes en curso). */
    status: string | null;
    signal_date: string | null;
    close: number | null;
    price_date: string | null;
    source: string | null;
    price_verified: boolean | null;
    confirmed_level: number | null;
    confirmed_period: string | null;
    /** 4X claro: nivel 4 confirmado y vigente con precio verificado. */
    clear_price_signal: boolean | null;
    change: RadarDcaChange;
    formula_version: string | null;
    /** Fecha del barrido que produjo la fila: la vigencia se muestra, no se adivina. */
    scan_date: string;
}

export interface RadarDcaCoverage {
    universe: number;
    evaluated: number;
    ok: number;
    invalid: number;
    stale: number;
}

export interface RadarDcaResult {
    as_of: string;
    page: number;
    page_size: number;
    total: number;
    has_more: boolean;
    items: RadarDcaOpportunity[];
    counts_by_level: Record<string, number>;
    sectors: string[];
    coverage: RadarDcaCoverage;
}

export interface RadarDcaQuery {
    page?: number;
    level?: number | null;
    sector?: string | null;
    outsideTracked?: boolean;
}

/** Radar ProPicks+DCA (nico-v1): oportunidades del barrido acotado. Solo lectura. */
export async function getRadarDcaOpportunities(query: RadarDcaQuery = {}): Promise<RadarDcaResult> {
    const params = new URLSearchParams();
    params.set('page', String(query.page ?? 1));
    if (query.level != null) params.set('level', String(query.level));
    if (query.sector) params.set('sector', query.sector);
    if (query.outsideTracked) params.set('outside_tracked', 'true');
    return researchRequest<RadarDcaResult>(`/api/propicks/radar/opportunities?${params.toString()}`);
}
