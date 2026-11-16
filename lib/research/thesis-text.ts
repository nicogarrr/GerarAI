// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types (guards).
import { frameworkTerm } from './framework-terms.ts';
// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types (guards).
import { metricLabel } from './metric-labels.ts';
// @ts-expect-error explicit extension for node guards.
import { thesisCodeLabel } from './thesis-code-label.ts';

const es = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 });
const esSmall = new Intl.NumberFormat('es-ES', { maximumSignificantDigits: 3 });
const esMid = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 });

/** Decimal largo del backend (-0.006019747112082423, 70918000.000000) -> es-ES legible. */
function shortNumber(raw: string): string {
    const value = Number(raw);
    if (!Number.isFinite(value)) return raw;
    const abs = Math.abs(value);
    if (abs >= 1000) return es.format(value);
    if (abs < 1) return esSmall.format(value);
    return esMid.format(value);
}

/**
 * Limpia prosa de tesis que el backend persiste con restos técnicos: claves
 * snake_case, decimales de 4+ cifras y puntuación doble ("..", "?."). Solo se
 * toca la presentación; el texto guardado no cambia.
 */
// Siglas y claves cortas de una sola palabra que el backend antiguo persistió
// en crudo dentro de prosa española («faltan valor contable, roe, aum, nav»,
// medido en prod 19 oct 2026 en resúmenes de CB/BN): la regla snake_case no
// las toca porque no llevan guion bajo. Lista cerrada de siglas financieras
// (ninguna es palabra de prosa española); lo demás sigue intacto. La guarda
// de contexto replica la regla snake_case (sin letra/dígito/_/./@/- pegados) y
// además excluye '?' y '=' alrededor: los tokens dentro de URLs y query
// strings (https://x.com/nav/roe?eps=1) no se tocan.
const SHORT_KEY = /(?<![\w/.@?=-])(?:roe|roa|roic|eps|ebitda|wacc|aum|nav|arr|arpu|noi|tpv|rpo|sbc)(?![\w/?=-])/g;

function missingTokens(text: string): string {
    // Source quotations are evidence, never Python-style missing values.
    return text.split(/("[^"\n]*"|'[^'\n]*'|«[^»\n]*»|“[^”\n]*”)/g).map((part, index) => {
        if (index % 2) return part;
        return part.replace(/\bNone\b(?=[:=]|\s*(?:$|[.,;](?=\s|$)))/gm, 'N/D');
    }).join('');
}

function sourceParts(text: string): string[] {
    return text.split(/(```[\s\S]*?```|https?:\/\/[^\s<>]+)/g);
}

export function cleanThesisText(text: string | null | undefined): string {
    if (!text) return text ?? '';
    return sourceParts(text).map(part => {
        if (part.startsWith('http') || part.startsWith('```')) return part;
        return missingTokens(part)
        .replace(/\b(?:unassigned|preview_only|fact_anchored_sensitivity)\b/g, thesisCodeLabel)
        .replace(/(?<![\w/.@-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w/-])/g, (token) => {
            const known = frameworkTerm(token) ?? metricLabel(token);
            return known.replaceAll('_', ' ');
        })
        .replace(SHORT_KEY, (token) => frameworkTerm(token) ?? metricLabel(token))
        .replace(/(?<![\w.])-?\d+\.\d{4,}(?![\d.]*\d\.)/g, (num) => shortNumber(num))
        .replace(/([?!])\.(?!\.)/g, '$1')
        .replace(/(?<!\.)\.{2}(?!\.)/g, '.');
    }).join('');
}

const isoDate = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Madrid' });
const isoCalendarDate = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const ISO_TIMESTAMP = /(?<![\d-])\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?(?![\d:])/g;
// Decimal con punto pegado a % ("36.2%") -> "36,2 %" como el resto de la ficha.
const DOT_PERCENT = /(?<![\w.])(-?\d{1,3}\.\d{1,2})\s?%/g;

/** Fechas ISO y porcentajes con punto -> es-ES. Solo presentacion; el resto intacto. */
export function localizeMemoNumbers(text: string): string {
    return text
        .replace(ISO_TIMESTAMP, (iso) => {
            const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
            const date = new Date(zoned ? iso : `${iso}Z`);
            return Number.isNaN(date.getTime()) ? iso : (zoned ? isoDate : isoCalendarDate).format(date);
        })
        .replace(DOT_PERCENT, (_m, num: string) => `${num.replace('.', ',')}\u00A0%`);
}

/** Presentation of legacy memoranda only. Preserve URLs, citations and numbers. */
export function cleanThesisMarkdown(text: string): string {
    const withoutDuplicateNarrative = text.replace(/\n## 24\. Análisis narrativo INFERIDO[\s\S]*?(?=\n## (?!#)|$)/g, '');
    return sourceParts(withoutDuplicateNarrative).map(part => {
        if (part.startsWith('http') || part.startsWith('```')) return part;
        return missingTokens(localizeMemoNumbers(part))
            .replace(/\b(?:unassigned|preview_only|fact_anchored_sensitivity)\b/g, thesisCodeLabel)
            .replace(/Análisis narrativo INFERIDO/g, 'Análisis narrativo')
            .replace(/median of latest annual FCF margins/g, 'Mediana de los últimos márgenes FCF anuales')
            .replace(/annual revenue CAGR across available history/g, 'CAGR anual de ingresos del historial disponible')
            .replace(/diluted share count CAGR across available history/g, 'CAGR de acciones diluidas del historial disponible');
    }).join('');
}
