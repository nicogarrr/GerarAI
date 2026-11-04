import { expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";

/**
 * Con el idioma en inglés, las cifras y fechas van en formato inglés en las
 * vistas principales (4-nov-2026: el barrido E2E local en `en` encontró
 * «+87,2 %», «630,00 US$», «19 nov 2026» en el vistazo rápido de la ficha y
 * «Último post-cierre · …: 206,15 US$» / «633,13 US$ +26,6 %» en la
 * watchlist). Solo comprueba AUSENCIA de formato castellano: si la fila no
 * tiene dato (sin red) no se pinta y la prueba sigue valiendo.
 */
const SPANISH_FORMAT = /\d,\d+\s?%|\d,\d{2}\s?(?:US\$|€|£)|\bUS\$|\b\d{1,2} (?:ene|feb|mar|abr|may|jun|jul|ago|sept?|oct|nov|dic)\.? \d{4}\b|Último (?:post-cierre|premercado)/;

for (const vp of VIEWPORTS) {
  test.describe(`inglés: formato de cifras y fechas (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);

    for (const route of ["/watchlist", "/research/MSFT"]) {
      test(`${route} en inglés sin cifras ni fechas en formato castellano`, async ({ page, context, baseURL, health }) => {
        // Aviso de React en desarrollo, ajeno a este spec y pendiente aparte:
        // LocaleProvider (lib/i18n/client.tsx) encadena dos use() condicionales
        // (castellano y luego inglés) y al reanudar React reutiliza la promesa
        // anterior. Se documenta aquí para que el spec mida el formato.
        health.allowConsole(/suspended by an uncached promise/);
        await context.addCookies([{ name: "gerarai_locale", value: "en", url: baseURL ?? "http://127.0.0.1:3100" }]);
        await visit(page, route);
        await expectHealthyPage(page, `${route} en`);
        const offending = await page.evaluate((src) => {
          const re = new RegExp(src);
          return document.body.innerText.split("\n").map((l) => l.trim()).filter((l) => re.test(l)).slice(0, 8);
        }, SPANISH_FORMAT.source);
        expect(offending, `${route} en inglés`).toEqual([]);
      });
    }
  });
}
