/** Count only recorded result IDs; an absent result is not zero. */
export function extractionResultText(job: { status: string; result: Record<string, unknown>; error: string | null } | undefined): string | null {
  if (!job) return null;
  if (job.status === 'failed') return job.error || 'No se pudo completar la extracción.';
  if (job.status !== 'completed' && job.status !== 'partial') return null;
  const ids = job.result.principle_ids;
  const count = Array.isArray(ids) ? ids.length : null;
  const result = count === null ? 'Recuento no disponible.' : `${count} principios encontrados.`;
  return `${job.status === 'partial' ? 'Extracción parcial' : 'Extracción completada'}: ${result}`;
}

const DEFAULT_NAMES = ['Buffett & Munger', 'Howard Marks', 'Fundsmith', 'Numantia', 'Capital Allocation', 'Cyclicals', 'Compounders', 'Pre-revenue', 'Space Industry', 'Personal Mistakes'];
export function hasDefaultCollections(collections: { name: string }[]): boolean {
  return DEFAULT_NAMES.every(name => collections.some(collection => collection.name === name));
}

/** Empty-state de la pestaña Principios cuando no existe ninguno todavía:
 *  distingue "nunca se ha extraído" de una extracción silenciosa que terminó
 *  sin principios, parcial o fallida, para que la página no muera en un
 *  "Ningún principio coincide" sin contexto. */
export function noPrinciplesText(
  jobs: { status: string; result: Record<string, unknown>; error: string | null }[],
): string {
  const latest = jobs.find(
    (job) => job.status === 'completed' || job.status === 'partial' || job.status === 'failed',
  );
  if (!latest) return 'Aún no hay principios extraídos.';
  if (latest.status === 'failed') {
    return latest.error
      ? `La última extracción falló: ${latest.error}`
      : 'La última extracción falló.';
  }
  const ids = latest.result.principle_ids;
  const count = Array.isArray(ids) ? ids.length : null;
  if (count !== null && count > 0) return 'Aún no hay principios extraídos.';
  if (latest.status === 'partial') return 'La última extracción se quedó a medias y no dejó principios.';
  if (count === 0) return 'La última extracción terminó sin encontrar principios.';
  return 'Aún no hay principios extraídos.';
}
