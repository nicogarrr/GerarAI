/**
 * Rutas que e2e/global-setup.ts compila antes del primer test de la suite UI
 * (E2E_UI_RUN=1).
 *
 * `next dev` compila cada ruta y sus chunks de cliente la primera vez que un
 * navegador los pide. Sin calentar, esa compilación cae dentro del primer
 * test que visita la ruta y se come sus timeouts de `expect`: caso medido en
 * company-header-quote.spec.ts (móvil), donde la figure «Evolución del
 * precio» falta porque el chunk dinámico de CompanyTechnicalChart sigue
 * compilándose cuando expira el expect (precio y variación son SSR y sí
 * aparecen). No es un bug de UI: en caliente la figure monta en ~5 s.
 *
 * La lista cubre las rutas que visitan los specs de e2e/user-flows (lo
 * comprueba tests/unit/e2e/warmup-routes.test.ts, sin query ni hash) más las
 * rutas con chunks de cliente pesados del resto de la suite UI (gráficos y
 * grafos). `/research/MSFT` compila /research/[ticker], la ruta con el chunk
 * dinámico más caro de la app.
 *
 * E2E_WARMUP_ROUTES (separada por comas) sustituye la lista, pensado para
 * validar el calentamiento en local sin esperar todas las rutas:
 *   E2E_WARMUP_ROUTES=/research/MSFT E2E_UI_RUN=1 npx playwright test ...
 */
const DEFAULT_WARMUP_ROUTES = [
  "/inicio",
  "/portfolio",
  "/research/MSFT",
  "/research/MSFT/tesis",
  "/watchlist",
  "/taxes",
  "/alerts",
  "/settings",
  "/knowledge-graph",
  "/knowledge",
  "/screener",
  "/propicks",
  "/no-existe-e2e-flujos",
] as const;

const override = process.env.E2E_WARMUP_ROUTES?.split(",").map((route) => route.trim()).filter(Boolean);

export const WARMUP_ROUTES: readonly string[] = override && override.length > 0 ? override : DEFAULT_WARMUP_ROUTES;

export const PER_ROUTE_BUDGET_MS = 120_000;

export function isRetryableWarmup(status: number | null, error: string | null): boolean {
  if (error) return /ERR_ABORTED|ERR_CONNECTION_(REFUSED|RESET)|ERR_EMPTY_RESPONSE|Timeout|socket hang up/i.test(error);
  return status === null || status >= 500;
}
