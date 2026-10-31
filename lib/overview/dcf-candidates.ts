/**
 * F65: la tarjeta «Oportunidades por valor intrínseco» del inicio declaraba
 * alcance de universo («Todo el universo del screener», «Ninguna empresa del
 * universo supera hoy un 5 %…») probando solo las primeras 6 candidatas y
 * tratando igual un DCF fallido que un potencial insuficiente. Aquí vive el
 * alcance real de la sonda y los textos honestos que lo declaran.
 */

import type { TranslateFn } from '@/lib/i18n/translate';

/** Candidatas del screener que se prueban por visita (DCF + precio). */
export const DCF_CANDIDATE_LIMIT = 6;

/** Umbral de potencial (%) para listar una oportunidad. */
export const DCF_MIN_UPSIDE_PCT = 5;

export type DcfProbeOutcome<T> = {
    /** true = el DCF y el precio se pudieron leer (la candidata cuenta). */
    evaluated: boolean;
    opportunity: T | null;
};

export type DcfScope = {
    /** Candidatas intentadas (como mucho DCF_CANDIDATE_LIMIT). */
    probed: number;
    /** Con DCF y precio válidos. */
    evaluated: number;
    /** Sin DCF/precio o con error: no dicen nada sobre su potencial. */
    failed: number;
};

export function summarizeDcfProbe<T>(outcomes: DcfProbeOutcome<T>[]): DcfScope {
    const evaluated = outcomes.filter((outcome) => outcome.evaluated).length;
    return { probed: outcomes.length, evaluated, failed: outcomes.length - evaluated };
}

/** Alcance real cuando hay oportunidades que mostrar. */
export function dcfScopeNote(t: TranslateFn, scope: DcfScope, marketCapLabel: string): string {
    const vars = { probed: scope.probed, cap: marketCapLabel, failed: scope.failed };
    return scope.failed > 0 ? t('home.dcf.scopeWithFailures', vars) : t('home.dcf.scopeOk', vars);
}

/**
 * Estado vacío honesto: distingue «evaluadas y ninguna supera el umbral» de
 * «no se pudo evaluar», que no permite concluir nada sobre el potencial.
 */
export function dcfEmptyNote(t: TranslateFn, scope: DcfScope): string {
    if (scope.probed === 0) {
        return t('home.dcf.noCandidates');
    }
    if (scope.evaluated === 0) {
        return t('home.dcf.noneEvaluated', { probed: scope.probed });
    }
    const vars = { evaluated: scope.evaluated, min: DCF_MIN_UPSIDE_PCT, failed: scope.failed };
    return scope.failed > 0 ? t('home.dcf.noneAboveWithFailures', vars) : t('home.dcf.noneAbove', vars);
}
