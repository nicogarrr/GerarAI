/**
 * View-model puro de las pantallas unificadas de ProPicks (contrato B1
 * `propicks-unified-v1`, GET /api/propicks/unified).
 *
 * Reglas de veracidad (2026-11-16, alineado con el contrato):
 *  - El estado de la vista se DECIDE desde `result.status` y `result.blocks`;
 *    el frontend no reevalúa ni mezcla bloques.
 *  - Un `Datum` con status distinto de 'ok' es AUSENCIA declarada: se muestra
 *    como «No disponible» (missingLabel de Veracidad), nunca como 0/50.
 *    El 0 real (status ok, value 0) sí se muestra.
 */

import type { components } from '@/lib/research/openapi.generated';

export type UnifiedResult = components['schemas']['UnifiedResult'];
export type UnifiedPick = components['schemas']['UnifiedPick'];
export type UnifiedDatum = components['schemas']['Datum'];
export type UnifiedErrorKind = 'timeout' | 'unauthenticated' | 'forbidden' | 'rate_limited' | 'unavailable' | 'invalid_response';

export const UNIFIED_SCHEMA_VERSION = 'propicks-unified-v1';

export type UnifiedFetch =
    | { ok: true; result: UnifiedResult }
    | { ok: false; errorKind: UnifiedErrorKind; retryAfterSeconds: number | null };

export interface UnifiedViewState {
    state: 'ok' | 'empty' | 'partial' | 'error';
    /** Bloques no-ok en el orden del contrato (quality, valuation, dca, tracking). */
    affectedBlocks: string[];
    /** Corte de datos declarado por el backend, nunca la hora de carga. */
    asOf: string;
    errorKind?: UnifiedErrorKind;
}

const BLOCK_ORDER = ['quality', 'valuation', 'dca', 'tracking'] as const;

/** El estado de la vista se decide desde el contrato; el frontend no improvisa. */
export function deriveUnifiedViewState(result: UnifiedResult): UnifiedViewState {
    const affectedBlocks = BLOCK_ORDER.filter((key) => result.blocks[key]?.status !== 'ok');
    const firstError = BLOCK_ORDER.map((key) => result.blocks[key]?.error?.kind).find((kind) => kind !== undefined);
    return {
        state: result.status,
        affectedBlocks,
        asOf: result.asOf,
        ...(result.status === 'error' && firstError ? { errorKind: firstError } : {}),
    };
}

export interface OpportunityRow {
    instrumentId: string;
    ticker: string;
    name: string | null;
    /** Score de calidad 0..100 del contrato; null = ausente (status no-ok). */
    qualityScore: number | null;
    qualityPassed: boolean | null;
    valuationStatus: UnifiedDatum['status'];
    valuationPrice: number | null;
    marginOfSafety: number | null;
    dcaLevel: number | null;
    dcaPeriodState: 'confirmed' | 'forming' | null;
    eligibility: UnifiedPick['eligibility']['state'];
    /** reasonCodes de calidad + revisión + listing, para UnifiedStateNotice. */
    reasonCodes: string[];
    asOf: string;
}

export interface TrackingRow {
    instrumentId: string;
    ticker: string;
    name: string | null;
    held: boolean;
    watched: boolean;
    /** Motivos de revisión declarados por el backend; nunca inventados. */
    reviewReasons: string[];
    asOf: string;
}

/** Fila de Seguimiento: solo lo que el contrato declara (held/watched + motivos). */
export function toTrackingRow(pick: UnifiedPick): TrackingRow {
    return {
        instrumentId: pick.instrumentId,
        ticker: pick.listing.ticker,
        name: pick.listing.name ?? null,
        held: pick.tracking.held === true,
        watched: pick.tracking.watched === true,
        reviewReasons: [...pick.reviewReasons],
        asOf: pick.asOf,
    };
}

/** Valor de un Datum solo si el contrato lo declara ok; ausencia -> null. */
function datumNumber(d: UnifiedDatum): number | null {
    if (d.status !== 'ok') return null;
    return typeof d.value === 'number' && Number.isFinite(d.value) ? d.value : null;
}

/** Fila de Oportunidades: cada cifra viene del contrato o se declara ausente. */
export function toOpportunityRow(pick: UnifiedPick): OpportunityRow {
    const reasonCodes = [
        ...pick.quality.reasonCodes,
        ...pick.reviewReasons,
        ...(pick.listing.instrumentStatus === 'cancelled' ? ['instrument_cancelled'] : []),
        ...(pick.listing.tradingStatus === 'suspended' ? ['trading_suspended'] : []),
        ...(pick.listing.status === 'delisted' ? ['delisted'] : []),
    ];
    return {
        instrumentId: pick.instrumentId,
        ticker: pick.listing.ticker,
        name: pick.listing.name ?? null,
        qualityScore: datumNumber(pick.quality.score),
        qualityPassed: pick.quality.passed ?? null,
        valuationStatus: pick.valuation.status,
        valuationPrice: datumNumber(pick.valuation.price),
        marginOfSafety: datumNumber(pick.valuation.marginOfSafety),
        dcaLevel: datumNumber(pick.dca.level),
        dcaPeriodState: pick.dca.periodState ?? null,
        eligibility: pick.eligibility.state,
        reasonCodes: [...new Set(reasonCodes)],
        asOf: pick.asOf,
    };
}
