// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS } from './research/metric-labels.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { SOURCE_LABELS, SOURCE_LABELS_EN } from './research/source-display.ts';
// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS_EN } from './research/metric-labels-en.ts';

type CopyLocale = 'es' | 'en';

/**
 * Copy del estado y la puntuación de una auditoría de fuentes (F243).
 *
 * Verdad del backend (source_auditor.py): la puntuación mide SOLO
 * afirmaciones materiales con fuente citada, menos 5 puntos por afirmación
 * de baja confianza. El bloqueo (passed=false) puede venir de afirmaciones
 * sin fuente, conflictos de datos o ausencia de traza de valoración — dos
 * de esas tres causas NO mueven la puntuación. Por eso una auditoría
 * bloqueada puede mostrar 100/100 y el texto debe decir qué mide y qué no.
 */

export function auditStatusLabel(passed: boolean, locale: CopyLocale = 'es'): string {
    if (locale === 'en') return passed ? 'passed' : 'blocked';
    return passed ? 'superada' : 'bloqueada';
}

export function auditScoreText(
    passed: boolean,
    score: number,
    formatScore: (value: number) => string,
    locale: CopyLocale = 'es',
): string {
    if (locale === 'en') {
        const baseEn = `claim-support score ${formatScore(score)}/100 (penalizes low confidence and a missing SEC/FMP reconciliation)`;
        return passed ? baseEn : `${baseEn} — measures citations only, not the reason for the block`;
    }
    const base = `puntuación de respaldo de afirmaciones ${formatScore(score)}/100 (penaliza baja confianza y una conciliación SEC/FMP ausente)`;
    return passed
        ? base
        : `${base} — mide solo citas, no el motivo del bloqueo`;
}

const FIX_LABELS: Record<string, string> = {
    'No calculation trace -> no valuation.': 'Sin traza de cálculo no hay valoración: faltan variables de entrada; completa los datos y regenera la tesis.',
    'Add source_id to every material claim.': 'Hay afirmaciones materiales sin fuente: añade el documento que las respalda y regenera la tesis.',
    'Resolve data conflicts before saving final thesis.': 'Hay datos en conflicto entre fuentes: resuélvelos antes de guardar la tesis final.',
    'SEC/FMP reconciliation missing for reported financial facts.': 'Falta contrastar los datos financieros de SEC y FMP.',
};

const FIX_LABELS_EN: Record<string, string> = {
    'No calculation trace -> no valuation.': 'No calculation trace, so no valuation: model inputs are missing; complete the data and regenerate the thesis.',
    'Add source_id to every material claim.': 'Some material claims have no source: add the document that supports them and regenerate the thesis.',
    'Resolve data conflicts before saving final thesis.': 'Sources disagree on some data: resolve the conflicts before saving the final thesis.',
    'SEC/FMP reconciliation missing for reported financial facts.': 'The financial data has not been cross-checked between SEC and FMP.',
};

function auditFixLabelEn(fix: string): string {
    if (FIX_LABELS_EN[fix]) return FIX_LABELS_EN[fix];
    const missing = /^Missing valuation inputs:\s*(.+?)\.?$/i.exec(fix) ?? /^Faltan entradas de valoración[^:]*:\s*(.+?)\.?$/.exec(fix);
    if (missing) {
        const labels = missing[1].split(/,\s*/).map((key) => METRIC_LABELS_EN[key] ?? METRIC_LABELS_EN[key.toLowerCase()] ?? key.replaceAll('_', ' '));
        return `Missing valuation inputs: ${labels.join(', ')}.`;
    }
    return fix.replace(/\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b/g,
        (token) => METRIC_LABELS_EN[token] ?? SOURCE_LABELS_EN[token] ?? SOURCE_LABELS[token] ?? token.replaceAll('_', ' '));
}

/** Motivo de bloqueo traducido (única traducción de required_fixes); un texto desconocido se muestra sin códigos internos. */
export function auditFixLabel(fix: string, locale: CopyLocale = 'es'): string {
    if (locale === 'en') return auditFixLabelEn(fix);
    if (FIX_LABELS[fix]) return FIX_LABELS[fix];
    const missing = /^Missing valuation inputs:\s*(.+?)\.?$/i.exec(fix);
    if (missing) return auditFixLabel(`Faltan entradas de valoración: ${missing[1]}.`);
    // «Faltan entradas de valoración (variables del modelo): a, b»: cada clave suelta
    // (también sin guion bajo, como aum o nav, o con comodín segment_*) por su etiqueta.
    const listed = /^(Faltan entradas de valoración[^:]*):\s*(.+?)(\.?)$/.exec(fix);
    if (listed) {
        const labels = listed[2].split(/,\s*/).map((key) => METRIC_LABELS[key] ?? METRIC_LABELS[key.toLowerCase()] ?? key.replaceAll('_', ' '));
        return `${listed[1]}: ${labels.join(', ')}${listed[3]}`;
    }
    return fix.replace(/\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b/g,
        (token) => METRIC_LABELS[token] ?? SOURCE_LABELS[token] ?? token.replaceAll('_', ' '));
}

/**
 * Auditorías recientes primero (created_at desc, id desc de desempate). El
 * panel de la ficha muestra solo la más reciente y pliega el historial: un
 * muro de versiones viejas repetía el mismo texto y se leía como bug
 * (informe UX 29-oct, punto 4).
 */
export function sortAuditsRecentFirst<T extends { id: number; created_at?: string | null }>(audits: readonly T[]): T[] {
    return [...audits].sort((left, right) => {
        const leftTs = left.created_at ?? '';
        const rightTs = right.created_at ?? '';
        if (leftTs !== rightTs) return leftTs < rightTs ? 1 : -1;
        return right.id - left.id;
    });
}
