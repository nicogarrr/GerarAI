import { expect, test } from "@playwright/test";

// Capturas REALES de la app para los mockups de la landing (hero multi-dispositivo),
// y verificacion visual de la propia landing. Se apoya en el fixture E2E determinista
// (misma semilla que company-header-quote): la cabecera de la ficha SIEMPRE llega a
// 336,56 US$; esperar un timeout fijo capturaba estados a medio cargar (N/D), asi que
// cada captura espera el dato, no el reloj.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const header = (page: import("@playwright/test").Page) => page.getByTestId("company-header-quote");

async function fichaLista(page: import("@playwright/test").Page, width: number, height: number) {
  await page.setViewportSize({ width, height });
  await page.goto("/research/MSFT");
  await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
  // Dato determinista del fixture: si no llega, la captura no es valida.
  await expect(header(page).getByText(/^336,56\sUS\$$/)).toBeVisible();
  await expect(page.getByTestId("company-technical-chart").getByRole("figure", { name: /Evolución del precio/ })).toBeVisible();
  // Sin desbordamiento horizontal: el layout debe caber en su viewport.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

test("landing shots: ficha MSFT desktop", async ({ page }) => {
  await fichaLista(page, 1440, 900);
  await page.goto("/research/MSFT?view=thesis");
  await expect(header(page).getByText(/^336,56\sUS\$$/)).toBeVisible();
  await page.screenshot({ path: "test-results/landing-desktop.png" });
});

test("landing shots: ficha MSFT tablet", async ({ page }) => {
  await fichaLista(page, 834, 1112);
  await page.screenshot({ path: "test-results/landing-tablet.png" });
});

test("landing shots: ficha MSFT movil", async ({ page }) => {
  await fichaLista(page, 390, 844);
  await page.screenshot({ path: "test-results/landing-mobile.png" });
});

// Espera de verdad, no de reloj: en un runner lento (CI) las tipografías y los
// mockups llegan tarde, y el mockup de móvil nace BAJO el fold (next/image lazy):
// sin traerlo a vista puede no empezar a cargar nunca. Medir overflow o capturar
// antes de que fuentes e imágenes asienten da resultados distintos por entorno.
// `alts` son los mockups VISIBLES en ese viewport: el de tablet es `hidden lg:block`
// por diseño y esperarlo en 390px es esperar lo imposible.
async function landingAsentada(page: import("@playwright/test").Page, alts: RegExp[]) {
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  for (const alt of alts) {
    const img = page.getByAltText(alt);
    await img.scrollIntoViewIfNeeded();
    await expect(img).toBeVisible({ timeout: 30_000 });
  }
  // Esas imágenes con píxeles de verdad (naturalWidth), no solo en el DOM.
  await page.waitForFunction(
    (wanted) => {
      const matches = Array.from(document.querySelectorAll("img")).filter((i) =>
        wanted.some((w) => i.alt.includes(w)),
      );
      // Sin el count, una lista vacía pasaría el every() sin haber visto nada.
      return matches.length === wanted.length && matches.every((i) => i.complete && i.naturalWidth > 0);
    },
    alts.map((a) => a.source),
  );
  // Tipografías cargadas: el ancho del texto cambia con la fuente y el overflow
  // medido antes del swap no es el overflow real.
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
}

test("landing shots: landing desktop fullpage", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await landingAsentada(page, [/Ficha de empresa de GerarAI/, /GerarAI en tablet/, /GerarAI en móvil/]);
  await page.screenshot({ path: "test-results/landing-page-desktop.png", fullPage: true });
});

test("landing shots: landing movil fullpage", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await landingAsentada(page, [/Ficha de empresa de GerarAI/, /GerarAI en móvil/]);
  // Sin desbordamiento horizontal: el layout debe caber en 390px de verdad.
  // El mensaje nombra a los culpables: la próxima CI roja dice QUÉ se sale,
  // no solo cuánto.
  const overflowInfo = await page.evaluate(() => {
    const doc = document.documentElement;
    const offenders = Array.from(document.querySelectorAll("body *"))
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.right > doc.clientWidth + 1 || r.left < -1)
      .slice(0, 8)
      .map(({ el, r }) => {
        const cls = typeof el.className === "string" ? el.className.trim().slice(0, 60) : "";
        const txt = (el.textContent ?? "").trim().slice(0, 40);
        return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""} [${Math.round(r.left)}..${Math.round(r.right)}] "${txt}"`;
      });
    return { excess: doc.scrollWidth - doc.clientWidth, scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth, offenders };
  });
  expect(
    overflowInfo.excess,
    `overflow: scrollWidth=${overflowInfo.scrollWidth} client=${overflowInfo.clientWidth}; offenders: ${overflowInfo.offenders.join(" | ") || "ninguno >1px"}`,
  ).toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/landing-page-mobile.png", fullPage: true });
});
