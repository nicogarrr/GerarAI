// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

/** Do not merge claims across thesis versions or assign unknown ids a version. */
export function groupClaimsByVersion<T extends { thesis_version_id: number | null }>(
  claims: T[], versions: Array<{ id: number; version: number }>, ti: TiFn = esT,
): Array<{ key: string; label: string; claims: T[] }> {
  const numbers = new Map(versions.map(version => [version.id, version.version]));
  const groups = new Map<string, { key: string; label: string; claims: T[] }>();
  for (const claim of claims) {
    const id = claim.thesis_version_id;
    const key = id == null ? 'manual' : `thesis-${id}`;
    const version = id == null ? null : numbers.get(id);
    const label = id == null ? ti('research.claimGroups.manual')
      : version == null ? ti('research.claimGroups.unknownVersion', { id }) : ti('research.claimGroups.version', { version });
    if (!groups.has(key)) groups.set(key, { key, label, claims: [] });
    groups.get(key)!.claims.push(claim);
  }
  return [...groups.values()];
}
