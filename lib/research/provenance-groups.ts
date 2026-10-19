// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { METRIC_LABELS } from './metric-labels.ts';
export type ProvenanceGroup = 'reportado' | 'sin_verificar' | 'calculado' | 'supuesto';

export const PROVENANCE_GROUPS: ReadonlyArray<{ key: ProvenanceGroup; title: string }> = [
  { key: 'reportado', title: 'Reportado' },
  { key: 'sin_verificar', title: 'Reportado, fuente sin verificar' },
  { key: 'calculado', title: 'Calculado de reportados' },
  { key: 'supuesto', title: 'Supuestos del modelo' },
];

/** dato = cifra reportada con cita; derivado = cálculo sobre cifras reportadas;
 *  el resto (política, usuario, estimación) es un supuesto del modelo. */
export function provenanceGroup(label: string | null | undefined, verified = true): ProvenanceGroup {
  if (label === 'dato') return verified ? 'reportado' : 'sin_verificar';
  if (label === 'derivado') return 'calculado';
  return 'supuesto';
}

const BASIS_ES: ReadonlyArray<[RegExp, string]> = [
  [/^median of latest annual FCF margins$/i, 'Mediana de los últimos márgenes FCF anuales'],
  [/^annual revenue CAGR across available history$/i, 'CAGR anual de ingresos en el historial disponible'],
  [/^diluted share count CAGR across available history$/i, 'CAGR de las acciones diluidas en el historial disponible'],
  [/^diluted share count CAGR$/i, 'CAGR de las acciones diluidas'],
];

/** Periodo guardado como dato estructurado («2025-09-27:FY») pintado en
 *  español natural: ni ISO ni sufijo crudo en la UI (visto en prod con AAPL,
 *  19-oct-2026: «Reportado, período 2025-09-27:FY»). Solo cambia la
 *  presentación; el dato almacenado no se toca. */
export function periodoEs(period: string): string {
    const m = /^(\d{4})-(\d{2})-(\d{2}):(FY|Q[1-4]|TTM|H[12])$/.exec(period.trim());
    if (!m) return period;
    const fecha = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
        .format(new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))));
    if (m[4] === 'FY') return `ejercicio fiscal ${m[1]} (cierre ${fecha})`;
    if (m[4] === 'TTM') return `últimos doce meses a ${fecha}`;
    if (m[4][0] === 'Q') return `T${m[4][1]} ${m[1]} (cierre ${fecha})`;
    return `${m[4]} ${m[1]} (cierre ${fecha})`;
}

/** Texto de la base en español; sin el prefijo "dado" y sin inglés conocido. */
export function provenanceBasisEs(base: string | null | undefined): string | null {
  const clean = (base ?? '').trim().replace(/^dado\s+/i, '');
  if (!clean) return null;
  for (const [pattern, text] of BASIS_ES) if (pattern.test(clean)) return text;
  // Claves sin etiqueta propia se humanizan («free_cash_flow» → «free cash
  // flow»), nunca se pinta el snake_case crudo.
  const metricLabelFor = (key: string): string =>
    (METRIC_LABELS as Record<string, string>)[key]?.toLowerCase() ?? key.replace(/_/g, ' ');
  const median = /^mediana de las últimas (\d+) observaciones anuales de ([a-z_]+)$/i.exec(clean);
  if (median) {
    const count = Number(median[1]);
    // Datos guardados antes de la gramatica singular (F13): 1 -> singular, 0 -> sin observaciones.
    if (count === 1) return `Mediana de la última observación anual de ${metricLabelFor(median[2])}`;
    if (count === 0) return `Sin observaciones anuales de ${metricLabelFor(median[2])}`;
    return `Mediana de las últimas ${median[1]} observaciones anuales de ${metricLabelFor(median[2])}`;
  }
  const medianOne = /^mediana de la última observación anual de ([a-z_]+)$/i.exec(clean);
  if (medianOne) return `Mediana de la última observación anual de ${metricLabelFor(medianOne[1])}`;
  const none = /^sin observaciones anuales de ([a-z_]+)$/i.exec(clean);
  if (none) return `Sin observaciones anuales de ${metricLabelFor(none[1])}`;
  const reported = /^(.+?) reportado(?: \(periodo (.+)\))?$/.exec(clean);
  if (reported) return reported[2] ? `Reportado, ${periodoEs(reported[2])}` : 'Reportado';
  const sentence = clean.charAt(0).toUpperCase() + clean.slice(1);
  return sentence;
}
