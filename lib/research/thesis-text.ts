// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types (guards).
import { frameworkTerm } from './framework-terms.ts';
// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types (guards).
import { metricLabel } from './metric-labels.ts';

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
export function cleanThesisText(text: string | null | undefined): string {
    if (!text) return text ?? '';
    return text
        .replace(/(?<![\w/.@-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w/-])/g, (token) => {
            const known = frameworkTerm(token) ?? metricLabel(token);
            return known.replaceAll('_', ' ');
        })
        .replace(/(?<![\w.])-?\d+\.\d{4,}(?![\d.]*\d\.)/g, (num) => shortNumber(num))
        .replace(/([?!])\.(?!\.)/g, '$1')
        .replace(/(?<!\.)\.{2}(?!\.)/g, '.');
}
