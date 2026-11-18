import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type Page } from '@playwright/test';
test.skip(process.env.E2E_UI_RUN !== '1', 'Local UI fixture required');

// Regresión P21 (18-nov-2026): /plan desbordaba en horizontal a 320px
// (scrollWidth 343 medido en prod; la pista única del grid `grid gap-6` se
// iba a 327px sobre los 288 disponibles). Bisección en vivo sobre prod:
//  1. Cabecera de RecordDetail («Objetivo y asignación»): fila de botones
//     «Refrescar» + «Editar plan» en nowrap ≈ 253px de min-content → 301px.
//  2. Estado vacío de RecordList («Aportaciones»): CTA «Registrar
//     aportación» (whitespace-nowrap del Button base) ≈ 213px de min-content
//     dentro del EmptyState p-8 → 327px.
//
// Este spec no se fía de las clases: extrae las clases reales del fuente,
// monta las dos tarjetas con el cromo real (Card p-6, EmptyState p-8,
// paddings de página p-4) con el CSS real de la app y mide
// documentElement.scrollWidth a 320px. Incluye la versión con las clases
// antiguas que DEBE desbordar: si no discrimina, no vale.

const recordViewsSrc = readFileSync('components/data/RecordViews.tsx', 'utf8');
const dialogSrc = readFileSync('components/plan/PlanContributionDialog.tsx', 'utf8');
const buttonSrc = readFileSync('components/ui/button.tsx', 'utf8');

const headerRowClass = recordViewsSrc.match(/<div className="(flex[^"]*items-center gap-2)">\s*\{fetchRecord/)?.[1];
const triggerClass = dialogSrc.match(/<Button type="button" className="([^"]*min-h-\[44px\][^"]*)"/)?.[1];

const baseBtn = buttonSrc.match(/const buttonVariants = cva\(\s*"([^"]+)"/)?.[1] ?? '';
const sizeDefault = buttonSrc.match(/size:\s*\{\s*default: "([^"]+)"/)?.[1] ?? '';
const sizeSm = buttonSrc.match(/sm: "([^"]+)"/)?.[1] ?? '';
const variantDefault = buttonSrc.match(/variant:\s*\{\s*default: "([^"]+)"/)?.[1] ?? '';
const variantGhost = buttonSrc.match(/ghost: "([^"]+)"/)?.[1] ?? '';

// Mini tailwind-merge para la fixture estática: en la app `cn()` resuelve los
// conflictos quedándose con la clase posterior; en HTML plano manda el orden
// de la hoja, así que hay que quitar a mano las utilidades sobreescritas.
function mergeBtn(...parts: string[]): string {
    const tokens = parts.join(' ').split(/\s+/).filter(Boolean);
    const groups = ['h-', 'whitespace-', 'py-', 'px-', 'gap-'];
    const result: string[] = [];
    for (const token of tokens) {
        const group = groups.find(g => token.startsWith(g));
        if (group) {
            const existing = result.findIndex(t => t.startsWith(group));
            if (existing >= 0) result.splice(existing, 1);
        }
        result.push(token);
    }
    return result.join(' ');
}

const icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/></svg>';

function fixture(headerCls: string, ctaCls: string, prefix: string): string {
    const refrescar = `<button class="${mergeBtn(baseBtn, variantGhost, sizeSm, 'gap-2 text-gray-400')}">${icon}Refrescar</button>`;
    const editar = `<button class="${mergeBtn(baseBtn, variantDefault, sizeDefault, 'gap-2')}">${icon}Editar plan</button>`;
    const registrar = `<button class="${mergeBtn(baseBtn, variantDefault, sizeDefault, ctaCls)}">${icon}Registrar aportación</button>`;
    return `
    <div class="rounded-lg border border-gray-700 bg-gray-800/50">
        <div class="space-y-1.5 p-6 flex flex-col gap-3 border-b border-gray-700/50 pb-4 sm:flex-row sm:items-center sm:justify-between sm:space-y-0">
            <div class="flex items-center gap-3">${icon}<div>
                <h2 class="tracking-tight text-lg font-semibold text-gray-100">Objetivo y asignación</h2>
                <p class="mt-0.5 text-sm text-gray-500">Meta mensual y reparto objetivo</p>
            </div></div>
            <div data-testid="${prefix}-acciones" class="${headerCls}">${refrescar}${editar}</div>
        </div>
        <div class="p-6 pt-4"><p class="text-sm text-gray-200">Contenido</p></div>
    </div>
    <div class="rounded-lg border border-gray-700 bg-gray-800/50">
        <div class="space-y-1.5 p-6 flex flex-col gap-3 border-b border-gray-700/50 pb-4">
            <div class="flex items-center gap-3">${icon}<div>
                <h2 class="tracking-tight text-lg font-semibold text-gray-100">Aportaciones</h2>
            </div></div>
        </div>
        <div class="p-6 pt-4">
            <div class="rounded-lg border border-dashed border-gray-700/50 p-8 text-center">
                <p class="break-words text-base font-semibold text-gray-100 mt-3">Todavía no has registrado aportaciones</p>
                <div class="mt-4 flex justify-center" data-testid="${prefix}-vacio">${registrar}</div>
            </div>
        </div>
    </div>`;
}

async function realAppCss(page: Page): Promise<string> {
    await page.goto('/plan', { waitUntil: 'domcontentloaded' });
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

// Auditoría P21 v1 (18-nov-2026): las tarjetas nuevas y el control antiguo
// montados en el MISMO documento contaminan la medida — documentElement
// .scrollWidth es del documento entero y el control antiguo lo llevaba a 343
// también durante la aserción de las nuevas. Cada grupo va en SU PROPIO
// contexto/documento: las nuevas deben pasar y el control debe fallar.
async function isolatedFixture(browser: Browser, css: string, width: number, cards: string) {
    const context = await browser.newContext({ viewport: { width, height: 568 }, javaScriptEnabled: false });
    const page = await context.newPage();
    await page.setContent(`<style>${css}</style><main class="bg-gray-950 p-4 text-gray-200">
        <div class="grid gap-6" data-testid="rejilla">${cards}</div>
    </main>`);
    return { context, page };
}

const nuevas = () => fixture(headerRowClass ?? '', triggerClass ?? '', 'n');
const controlViejo = () => fixture('flex items-center gap-2', 'min-h-[44px] gap-2', 'v');

test.describe('/plan: sin desbordamiento horizontal a 320px', () => {
    test('las clases fuente son las parcheadas', () => {
        expect(headerRowClass, 'fila de botones de RecordDetail').toContain('flex-wrap');
        expect(triggerClass, 'disparador de PlanContributionDialog').toContain('whitespace-normal');
        expect(triggerClass, 'mantiene el mínimo táctil').toContain('min-h-[44px]');
    });

    test('320px: las tarjetas nuevas no desbordan', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const { context, page: f } = await isolatedFixture(browser, css, 320, nuevas());
        try {
            const medida = await f.evaluate(() => {
                const accionesN = document.querySelector('[data-testid="n-acciones"]');
                const hijos = accionesN ? Array.from(accionesN.children) : [];
                const ctaN = document.querySelector('[data-testid="n-vacio"] button');
                return {
                    scrollW: document.documentElement.scrollWidth,
                    envuelve: hijos.length === 2 ? (hijos[1] as HTMLElement).offsetTop > (hijos[0] as HTMLElement).offsetTop : null,
                    ctaAlto: ctaN ? Math.round((ctaN as HTMLElement).getBoundingClientRect().height) : 0,
                };
            });
            expect(medida.scrollW, 'scrollWidth con las clases parcheadas a 320px').toBeLessThanOrEqual(320);
            expect(medida.envuelve, 'los botones de cabecera envuelven a 320px').toBe(true);
            expect(medida.ctaAlto, 'el CTA conserva al menos 44px de alto').toBeGreaterThanOrEqual(44);
        } finally {
            await context.close();
        }
    });

    test('320px: control — las clases antiguas DEBEN desbordar (documento aparte)', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const { context, page: f } = await isolatedFixture(browser, css, 320, controlViejo());
        try {
            const scrollViejo = await f.evaluate(() => document.documentElement.scrollWidth);
            expect(scrollViejo, 'control: las clases antiguas DEBEN desbordar a 320px').toBeGreaterThan(320);
        } finally {
            await context.close();
        }
    });

    test('390px: tampoco desborda', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const { context, page: f } = await isolatedFixture(browser, css, 390, nuevas());
        try {
            const scrollW = await f.evaluate(() => document.documentElement.scrollWidth);
            expect(scrollW, 'scrollWidth a 390px').toBeLessThanOrEqual(390);
        } finally {
            await context.close();
        }
    });
});
