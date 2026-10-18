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
