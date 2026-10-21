/**
 * Decision pura para la vista activa de /research/[ticker]: que lectura fallida
 * cuenta como caida del motor. El predicado se inyecta (isBackendUnavailableError)
 * para que solo la caida reconocida degrade; todo lo demas se relanza.
 */
export type ViewSettledEntry =
  | { key: string; ok: true; value?: unknown }
  | { key: string; ok: false; reason: string; error?: unknown };

export function findUnavailableViewFailure(
  settled: readonly ViewSettledEntry[],
  isUnavailable: (error: unknown) => boolean,
): { key: string; reason: string } | null {
  for (const entry of settled) {
    if (!entry.ok && isUnavailable(entry.error)) return { key: entry.key, reason: entry.reason };
  }
  return null;
}

export function viewRetryHref(ticker: string, activeView: string): string {
  const view = activeView === 'overview' ? '' : `?view=${encodeURIComponent(activeView)}`;
  return `/research/${encodeURIComponent(ticker)}${view}`;
}
