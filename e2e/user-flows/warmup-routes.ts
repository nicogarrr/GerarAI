/**
 * Rutas que e2e/user-flows/global-setup.ts compila antes del primer test.
 * tests/unit/e2e/user-flows-warmup.test.ts comprueba que cubren todas las
 * rutas que visitan los specs de la suite (sin query ni hash).
 */
export const WARMUP_ROUTES = [
  "/inicio",
  "/portfolio",
  "/research/MSFT",
  "/research/MSFT/tesis",
  "/watchlist",
  "/taxes",
  "/alerts",
  "/settings",
  "/no-existe-e2e-flujos",
] as const;

export const PER_ROUTE_BUDGET_MS = 120_000;

export function isRetryableWarmup(status: number | null, error: string | null): boolean {
  if (error) return /ERR_ABORTED|ERR_CONNECTION_(REFUSED|RESET)|ERR_EMPTY_RESPONSE|Timeout|socket hang up/i.test(error);
  return status === null || status >= 500;
}
