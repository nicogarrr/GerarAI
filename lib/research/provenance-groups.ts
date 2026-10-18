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

/** Texto de la base en español; sin el prefijo "dado" y sin inglés conocido. */
export function provenanceBasisEs(base: string | null | undefined): string | null {
  const clean = (base ?? '').trim().replace(/^dado\s+/i, '');
  if (!clean) return null;
  for (const [pattern, text] of BASIS_ES) if (pattern.test(clean)) return text;
  const reported = /^(.+?) reportado(?: \(periodo (.+)\))?$/.exec(clean);
  if (reported) return reported[2] ? `Reportado, periodo ${reported[2]}` : 'Reportado';
  const sentence = clean.charAt(0).toUpperCase() + clean.slice(1);
  return sentence;
}
