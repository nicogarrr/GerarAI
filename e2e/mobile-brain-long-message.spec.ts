import { expect, test, type Page } from "@playwright/test";

import { mockBrainLayoutActions } from './fixtures/brain-layout-actions';

const runUiE2E = process.env.E2E_UI_RUN === "1";

// iPhone 14 viewport: 390x844 con táctil.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

// Un enlace o un token sin espacios (lo normal al pegar una URL de un 10-K o
// de una noticia) no puede quedar cortado dentro de la burbuja del Cerebro:
// la burbuja tiene overflow-hidden por las esquinas redondeadas, así que sin
// corte de palabra la mitad del texto quedaba oculta y sin forma de leerla.
const LONG_URL =
  "https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630_10K_annual_report_full_text.htm";
const LONG_TOKEN = "MSFT_TOKEN_MUY_LARGO_SIN_ESPACIOS_PARA_PROBAR_EL_CORTE_DE_LA_BURBUJA_DEL_CHAT";

async function expectNoPageOverflow(page: Page, step: string) {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(
    overflow.scrollWidth,
    `${step}: overflow horizontal scrollWidth=${overflow.scrollWidth} > innerWidth=${overflow.innerWidth}`,
  ).toBeLessThanOrEqual(overflow.innerWidth + 1);
}

test.describe("Cerebro a 390px: los mensajes largos no se cortan", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("un enlace largo se lee entero en la burbuja y la página no desborda", async ({ page }) => {
    await mockBrainLayoutActions(page, LONG_TOKEN);
    // /research/assistant abre el Cerebro (redirect de compatibilidad).
    await page.goto("/research/assistant");
    const dialog = page.getByRole("dialog");
    const input = page.locator("#global-brain-input");
    await expect(input).toBeVisible({ timeout: 30_000 });

    await input.fill(`Lee ${LONG_URL} y resume ${LONG_TOKEN}`);
    await expect(dialog.getByRole("button", { name: "Enviar pregunta", exact: true })).toBeEnabled();
    await input.press("Enter");

    const bubble = dialog.getByText(LONG_TOKEN, { exact: false }).first();
    await expect(bubble).toBeVisible({ timeout: 15_000 });

    // Ninguna burbuja recorta texto: lo que no cabe a lo ancho debe partirse
    // en líneas (scrollWidth == clientWidth), nunca quedar oculto.
    const clipped = await dialog.evaluate((root) => {
      const out: string[] = [];
      for (const el of Array.from(root.querySelectorAll<HTMLElement>("*"))) {
        if (!(el.textContent ?? "").includes("MSFT_TOKEN_MUY_LARGO")) continue;
        const style = getComputedStyle(el);
        if (style.overflowX === "auto" || style.overflowX === "scroll") continue;
        if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1) {
          out.push(`${el.tagName.toLowerCase()} scrollWidth=${el.scrollWidth} clientWidth=${el.clientWidth}`);
        }
      }
      return out;
    });
    expect(clipped, "texto cortado dentro de la burbuja del Cerebro").toEqual([]);

    // La burbuja no se sale del panel ni de la pantalla.
    const box = await bubble.boundingBox();
    expect(box, "burbuja con caja").not.toBeNull();
    expect(box!.x + box!.width).toBeLessThanOrEqual(391);
    await expectNoPageOverflow(page, "cerebro-mensaje-largo");
  });
});
