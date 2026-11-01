// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

/** Provider diagnostics stay in stored job errors, never in product copy. */
export function extractionFailureText(error: string | null, ti: TiFn = esT): string {
  if (/timeout|timed out|tiempo de espera/i.test(error ?? '')) return ti('knowledge.jobFeedback.timeout');
  if (/quota|rate.?limit|429|credit|crédito/i.test(error ?? '')) return ti('knowledge.jobFeedback.unavailable');
  return ti('knowledge.jobFeedback.failed');
}

/** Count only recorded result IDs; an absent result is not zero. */
export function extractionResultText(
  job: { status: string; result: Record<string, unknown>; error: string | null } | undefined,
  ti: TiFn = esT,
): string | null {
  if (!job) return null;
  if (job.status === 'failed') return extractionFailureText(job.error, ti);
  if (job.status !== 'completed' && job.status !== 'partial') return null;
  const ids = job.result.principle_ids;
  const count = Array.isArray(ids) ? ids.length : null;
  const result = count === null
    ? ti('knowledge.jobFeedback.countUnavailable')
    : ti(count === 1 ? 'knowledge.jobFeedback.principlesFoundOne' : 'knowledge.jobFeedback.principlesFound', { count });
  return ti(job.status === 'partial' ? 'knowledge.jobFeedback.partial' : 'knowledge.jobFeedback.completed', { result });
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
  ti: TiFn = esT,
): string {
  const latest = jobs.find(
    (job) => job.status === 'completed' || job.status === 'partial' || job.status === 'failed',
  );
  if (!latest) return ti('knowledge.jobFeedback.noPrinciples');
  if (latest.status === 'failed') {
    return extractionFailureText(latest.error, ti);
  }
  const ids = latest.result.principle_ids;
  const count = Array.isArray(ids) ? ids.length : null;
  if (count !== null && count > 0) return ti('knowledge.jobFeedback.noPrinciples');
  if (latest.status === 'partial') return ti('knowledge.jobFeedback.partialEmpty');
  if (count === 0) return ti('knowledge.jobFeedback.completedEmpty');
  return ti('knowledge.jobFeedback.noPrinciples');
}
