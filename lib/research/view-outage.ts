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

// El reintento apunta a la URL canónica de la pestaña (una fila de seis,
// 29-oct-2026), no al ?view= de módulo histórico.
import { MODULES, moduleHref } from '@/lib/research/research-views';

export function viewRetryHref(ticker: string, activeView: string): string {
  const mod = MODULES.find((m) => m.key === activeView);
  return mod ? moduleHref(ticker, mod) : `/research/${encodeURIComponent(ticker)}`;
}
