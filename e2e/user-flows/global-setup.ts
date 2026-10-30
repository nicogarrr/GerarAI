import { chromium, type FullConfig } from "@playwright/test";
import { isRetryableWarmup, PER_ROUTE_BUDGET_MS, WARMUP_ROUTES } from "./warmup-routes";

/**
 * Calentamiento de la suite de flujos (solo con E2E_USER_FLOWS=1).
 *
 * `next dev` compila cada ruta la primera vez que se pide. Sin calentar, esa
 * compilación (10-20 s por página en CI) cae dentro del primer test que visita
 * la ruta: se come sus timeouts de `expect`, y si dos compilaciones se solapan
 * Next responde un 500 «Manifest file is empty» o aborta la navegación
 * (ERR_ABORTED). Aquí se visita cada ruta de la suite una vez, en serie y con
 * un navegador real (así se compilan también los chunks de cliente y las rutas
 * /api que la página pide al hidratar), reintentando mientras el servidor de
 * desarrollo responda 5xx o corte la conexión. Los tests empiezan con todo
 * compilado y miden la app, no al compilador.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use?.baseURL ?? process.env.E2E_UI_URL ?? "http://127.0.0.1:3100";
  const browser = await chromium.launch();
  const started = Date.now();
  try {
    const page = await browser.newPage();
    for (const route of WARMUP_ROUTES) {
      const deadline = Date.now() + PER_ROUTE_BUDGET_MS;
      let last = "";
      for (let attempt = 1; ; attempt += 1) {
        let status: number | null = null;
        let error: string | null = null;
        try {
          const res = await page.goto(baseURL + route, { waitUntil: "domcontentloaded", timeout: 90_000 });
          status = res?.status() ?? null;
          await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => undefined);
        } catch (err) {
          error = String(err).slice(0, 200);
        }
        last = error ?? `HTTP ${status}`;
        if (!isRetryableWarmup(status, error)) break;
        if (Date.now() > deadline) {
          // No se aborta la suite: el test de esa ruta dará el fallo con su contexto.
          console.warn(`[user-flows warmup] ${route} sigue fallando tras ${attempt} intentos: ${last}`);
          break;
        }
        await new Promise((r) => setTimeout(r, 2_000));
      }
    }
  } finally {
    await browser.close();
  }
  console.log(`[user-flows warmup] ${WARMUP_ROUTES.length} rutas compiladas en ${Math.round((Date.now() - started) / 1000)} s`);
}
