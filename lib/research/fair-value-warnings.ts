/** The fair-value API already bounds warning count and length. Keep every
 * valid warning verbatim, in source order; never interpret warning text as HTML. */
export function fairValueWarnings(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return [...new Set(raw.filter((item): item is string => typeof item === 'string' && item.trim().length > 0))];
}
