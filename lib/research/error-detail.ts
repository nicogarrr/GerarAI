/**
 * Mensaje legible a partir del cuerpo de error del motor de análisis.
 *
 * FastAPI devuelve `detail` como texto en los errores de negocio, pero como
 * LISTA de objetos `{loc, msg, type}` en los 422 de validación (p. ej. una
 * métrica de 5.000 caracteres en el screener ad-hoc). Antes se hacía
 * `payload.detail ?? payload.message` y la lista acababa convertida a texto
 * como «[object Object]» en el banner de error. Aquí la lista se resume en
 * español con los campos rechazados; nunca se devuelve un no-texto.
 */
const LOCATION_PREFIXES = new Set(['body', 'query', 'path', 'header', 'cookie']);

function fieldOf(item: unknown): string | null {
  if (!item || typeof item !== 'object') return null;
  const loc = (item as { loc?: unknown }).loc;
  if (!Array.isArray(loc)) return null;
  // Último segmento con nombre: ["body", "criteria", 0, "left"] -> "left".
  const named = loc.filter(
    (part): part is string => typeof part === 'string' && part.trim() !== '' && !LOCATION_PREFIXES.has(part),
  );
  return named.length ? named[named.length - 1] : null;
}

function nonEmptyText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

export function researchErrorDetail(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback;
  const { detail, message } = payload as { detail?: unknown; message?: unknown };
  const text = nonEmptyText(detail);
  if (text) return text;
  if (Array.isArray(detail)) {
    const fields = [...new Set(detail.map(fieldOf).filter((field): field is string => field !== null))];
    return fields.length
      ? `Datos no válidos en: ${fields.join(', ')}. Revisa esos campos y vuelve a intentarlo.`
      : 'El motor de análisis rechazó los datos enviados. Revisa el formulario y vuelve a intentarlo.';
  }
  if (detail && typeof detail === 'object') {
    const inner = detail as { message?: unknown; detail?: unknown };
    const nested = nonEmptyText(inner.message) ?? nonEmptyText(inner.detail);
    if (nested) return nested;
  }
  return nonEmptyText(message) ?? fallback;
}
