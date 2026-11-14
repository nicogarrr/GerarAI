import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type Page } from '@playwright/test';
test.skip(process.env.E2E_UI_RUN !== '1', 'Local UI fixture required');
const source = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
// Tabla responsiva única (2026-11-14): la fecha de cierre vive en el <div> de la
// celda de precio (antes era un <dd> de la tarjeta móvil).
const dateClass = source.match(/<div className="([^"]+)">\{stock\.priceAsOf/)?.[1];

// El fixture NO se inyecta en la página de la app: React hidrata esa página y, si hay
// un mismatch, sustituye el documento (carrera vista en CI a 820px: el fixture era
// correcto tras setContent y ~350 ms después la aserción veía la Watchlist real).
// Se captura la CSS real de la app una vez y el fixture vive en un contexto aparte,
// sin ningún script de la app que pueda hidratarlo.
async function realAppCss(page: Page, width: number): Promise<string> {
  await page.setViewportSize({ width, height: 844 });
  await page.goto('/watchlist');
  await expect(page.getByRole('heading', { name: 'Watchlist', level: 1 })).toBeVisible();
  const sheets = await page.locator('link[rel=stylesheet]').evaluateAll(nodes => nodes.map(node => (node as HTMLLinkElement).href));
  expect(sheets.length).toBeGreaterThan(0);
  const css: string[] = [];
  for (const href of sheets) {
    const response = await page.request.get(href);
    expect(response.ok(), href).toBeTruthy();
    css.push(await response.text());
  }
  return css.join('\n');
}

async function isolatedFixture(browser: Browser, css: string, width: number) {
  const context = await browser.newContext({ viewport: { width, height: 844 }, javaScriptEnabled: false });
  const page = await context.newPage();
  // El fixture reproduce la celda de precio de la fila única (<tr> bloque en
  // móvil), no la tarjeta antigua.
  await page.setContent(`<style>${css}</style><main class="p-8 bg-gray-950 text-gray-200"><table class="block w-full text-sm"><tbody class="block space-y-3"><tr class="block rounded-xl border border-gray-700/60 p-3"><td class="block font-mono font-medium text-gray-200"><span class="block font-sans text-[11px] font-normal text-gray-500">Precio</span>29,47 US$<div data-testid="close-date" class="${dateClass}">Cierre 2026-10-06</div></td><td class="block">Market Cap $6.92B</td><td class="block">PER (TTM) N/D</td></tr></tbody></table></main>`);
  return { context, page };
}

for (const width of [320, 390, 820]) {
 test(`watchlist full close date remains readable at ${width}px`, async ({ page, browser }) => {
  expect(dateClass, 'clase de la fecha de cierre en watchlist/page.tsx').toBeTruthy();
  const css = await realAppCss(page, width);
  const { context, page: fixture } = await isolatedFixture(browser, css, width);
  try {
    const date = fixture.getByTestId('close-date');
    await expect(date).toBeVisible();
    // Ventana de la carrera original (~350 ms) y más: el fixture no puede cambiar.
    await fixture.waitForTimeout(1500);
    await expect(date).toBeVisible();
    await expect(date).toHaveText('Cierre 2026-10-06');
    expect(await fixture.evaluate(() => document.scripts.length)).toBe(0);
    const geometry = await date.evaluate(node => ({ width: node.clientWidth, scroll: node.scrollWidth, ellipsis: getComputedStyle(node).textOverflow }));
    expect(geometry.ellipsis).not.toBe('ellipsis');
    expect(geometry.scroll).toBeLessThanOrEqual(geometry.width + 1);
    await fixture.screenshot({ path: `test-results/watchlist-close-date-${width}.png` });
  } finally {
    await context.close();
  }
 });
}
