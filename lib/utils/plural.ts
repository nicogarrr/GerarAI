/**
 * «N nombre» con el número formateado en es-ES y el sustantivo en
 * singular/plural según N (1 escaneado / 20 escaneados).
 *
 * Vive en módulo propio porque lo usan tanto propicksSignals (SOLO servidor)
 * como insider-status-copy (llega al bundle cliente): importarlo desde
 * propicksSignals arrastraría un módulo server-only al cliente.
 */
// @ts-expect-error TS5097: extension explicita para node --experimental-strip-types (guards).
import { formatNumber } from '../format.ts';

export function plural(count: number, singular: string, pluralForm: string): string {
    return `${formatNumber(count, { maximumFractionDigits: 0 })} ${count === 1 ? singular : pluralForm}`;
}
