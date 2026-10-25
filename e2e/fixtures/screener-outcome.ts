import type { Page } from "@playwright/test";

export type ScreenerOutcome = "rows" | "down" | "empty";

/**
 * Espera una resolucion ACOTADA del screener: filas, o un estado final honesto
 * ("No hay datos ahora mismo" / "Sin resultados para"). "Cargando precios del
 * mercado en segundo plano" es transitorio y NUNCA cuenta como resultado: si
 * persiste tras el plazo, falla (no se da por verde una carga indefinida).
 * Recarga entre intentos porque la cache fria se rellena en segundo plano.
 */
export async function waitForScreenerOutcome(page: Page, totalMs = 60_000): Promise<ScreenerOutcome> {
  const deadline = Date.now() + totalMs;
  for (;;) {
    if ((await page.locator("table tbody tr").count()) > 0) return "rows";
    if ((await page.getByText("No hay datos ahora mismo").count()) > 0) return "down";
    if ((await page.getByText(/Sin resultados para/).count()) > 0) return "empty";
    if (Date.now() >= deadline) {
      throw new Error("screener sin resolver (filas o estado final honesto) en el plazo: carga indefinida");
    }
    await page.waitForTimeout(3_000);
    await page.reload();
  }
}
