import { expect, test, type Page } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

// iPhone 14 viewport: 390x844 con táctil.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

// La cabecera del Cerebro en móvil: una sola fila (antes ocupaba dos, ~135 px
// de 844), cada control con un área táctil de al menos 44x44 px, nada recortado
// ni fuera del panel, y lo que se acorta conserva su texto completo accesible.
// Con el inglés, que tiene textos más largos, igual.

const CASES = [
  { locale: "es", route: "/research/PLTR", title: "Cerebro GerarAI", open: "Abrir el cerebro", viewing: "Viendo PLTR", guide: "Abrir la guía de investigación por empresa" },
  { locale: "es", route: "/portfolio", title: "Cerebro GerarAI", open: "Abrir el cerebro", viewing: "Viendo Cartera", guide: "Abrir la guía de investigación por empresa" },
  { locale: "en", route: "/research/PLTR", title: "GerarAI Brain", open: "Open the brain", viewing: "Viewing PLTR", guide: "Open the per-company research guide" },
  { locale: "en", route: "/portfolio", title: "GerarAI Brain", open: "Open the brain", viewing: "Viewing", guide: "Open the per-company research guide" },
] as const;

type HeaderReport = {
  height: number;
  headerLeft: number;
  headerRight: number;
  controls: { label: string; width: number; height: number; left: number; right: number }[];
  clipped: string[];
};

// La cabecera es el hijo directo del diálogo que contiene el título.
async function measureHeader(page: Page): Promise<HeaderReport> {
  return page.evaluate(() => {
    const title = document.getElementById("global-brain-title");
    const dialog = title?.closest('[role="dialog"]');
    if (!title || !dialog) throw new Error("sin título o sin diálogo del Cerebro");
    let header: HTMLElement = title;
    while (header.parentElement && header.parentElement !== dialog) header = header.parentElement;
    const hb = header.getBoundingClientRect();
    const controls = Array.from(header.querySelectorAll<HTMLElement>("button, a[href], input"))
      .filter((el) => el.getClientRects().length > 0)
      .map((el) => {
        const r = el.getBoundingClientRect();
        return {
          label: el.getAttribute("aria-label") || el.textContent?.trim() || el.tagName.toLowerCase(),
          width: r.width,
          height: r.height,
          left: r.left,
          right: r.right,
        };
      });
    const clipped: string[] = [];
    for (const el of Array.from(header.querySelectorAll<HTMLElement>("*"))) {
      const style = getComputedStyle(el);
      // Texto solo para lectores de pantalla (sr-only): 1x1 px a propósito.
      if (style.position === "absolute" && el.clientWidth <= 1) continue;
      if (style.display === "none" || el.getClientRects().length === 0) continue;
      if (style.overflowX === "auto" || style.overflowX === "scroll") continue;
      if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1) {
        clipped.push(`${el.tagName.toLowerCase()} «${(el.textContent ?? "").trim().slice(0, 40)}» scrollWidth=${el.scrollWidth} clientWidth=${el.clientWidth}`);
      }
    }
    return { height: hb.height, headerLeft: hb.left, headerRight: hb.right, controls, clipped };
  });
}

function expectUsableOneRow(report: HeaderReport, step: string) {
  expect(report.height, `${step}: la cabecera ocupa más de una fila (${report.height}px)`).toBeLessThanOrEqual(64);
  expect(report.controls.length, `${step}: sin controles en la cabecera`).toBeGreaterThanOrEqual(3);
  for (const c of report.controls) {
    expect(c.width, `${step}: «${c.label}» mide ${c.width}px de ancho (<44)`).toBeGreaterThanOrEqual(44);
    expect(c.height, `${step}: «${c.label}» mide ${c.height}px de alto (<44)`).toBeGreaterThanOrEqual(44);
    expect(c.left, `${step}: «${c.label}» se sale por la izquierda`).toBeGreaterThanOrEqual(report.headerLeft - 0.5);
    expect(c.right, `${step}: «${c.label}» se sale por la derecha`).toBeLessThanOrEqual(Math.min(report.headerRight, 390) + 0.5);
  }
  expect(report.clipped, `${step}: texto recortado en la cabecera`).toEqual([]);
}

test.describe("Cerebro a 390px: cabecera en una fila y usable", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  for (const c of CASES) {
    test(`${c.locale} ${c.route}: una fila, controles de 44px, nada recortado`, async ({ page, context, baseURL }) => {
      await context.addCookies([{ name: "gerarai_locale", value: c.locale, url: baseURL ?? "http://127.0.0.1:3000" }]);
      await page.goto(c.route);
      await page.getByRole("button", { name: c.open }).first().click({ timeout: 60_000 });
      const dialog = page.getByRole("dialog", { name: c.title });
      await expect(dialog).toBeVisible({ timeout: 30_000 });
      // El nombre completo del panel y de la pastilla siguen accesibles aunque
      // en móvil se muestren abreviados.
      await expect(page.locator("#global-brain-title")).toContainText(c.title);
      await expect(dialog.getByTestId("brain-page-context")).toContainText(c.viewing);
      await expect(dialog.getByRole("button", { name: c.guide })).toBeVisible();

      expectUsableOneRow(await measureHeader(page), `${c.locale} ${c.route}`);

      // Con el selector de la guía abierto la cabecera sigue en una fila.
      await dialog.getByRole("button", { name: c.guide }).click();
      await expect(dialog.locator("input").first()).toBeVisible();
      expectUsableOneRow(await measureHeader(page), `${c.locale} ${c.route} + guía`);
    });
  }
});
