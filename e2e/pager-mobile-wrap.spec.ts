import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type Page } from '@playwright/test';
test.skip(process.env.E2E_UI_RUN !== '1', 'Local UI fixture required');

// Regresión P24 (18-nov-2026, medido en prod a 320px): el paginador Pager
// desbordaba — documentElement.scrollWidth 337, botón «Siguiente» hasta
// x=337 (17px fuera). Fila flex sin wrap + texto irrompible.
// Fix: texto a su propia línea en móvil (order-first w-full) + flex-wrap.
//
// Fixture aislada con el CSS real de la app; clases extraídas del fuente.
// Control con las clases antiguas en DOCUMENTO APARTE (lección P21).

const pagerSrc = readFileSync('components/research/Pager.tsx', 'utf8');

const navClass = pagerSrc.match(/<nav aria-label=\{t\('ui\.pagination\.ariaOf'[^)]*\)\} className="([^"]+)"/)?.[1];
const spanClass = pagerSrc.match(/<span aria-live="polite" className="([^"]+)"/)?.[1];
const btnClass = pagerSrc.match(/const btn = '([^']+)'/)?.[1];

const OLD_NAV = 'mt-4 flex items-center justify-between gap-3';
const OLD_SPAN = 'text-xs text-gray-400';

function pager(navCls: string, spanCls: string): string {
    // Textos reales (ui.json / researchShared.json, es) y etiqueta larga
    // representativa (RecordViews por defecto: «Registros»).
    return `<nav class="${navCls}" aria-label="Paginación de Registros">
        <button data-testid="prev" type="button" class="${btnClass}">Anterior</button>
        <span data-testid="info" class="${spanCls}"><span class="whitespace-nowrap">Página 1 de 25</span> · 2.345 Registros</span>
        <button data-testid="next" type="button" class="${btnClass}">Siguiente</button>
    </nav>`;
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

async function isolatedFixture(browser: Browser, css: string, width: number, body: string) {
    const context = await browser.newContext({ viewport: { width, height: 568 }, javaScriptEnabled: false });
    const page = await context.newPage();
    await page.setContent(`<style>${css}</style><main class="bg-gray-950 p-4 text-gray-200"><div class="rounded-xl border border-gray-800 p-4">${body}</div></main>`);
    return { context, page };
}

test.describe('P24: el paginador no desborda a 320px', () => {
    test('las clases fuente son las parcheadas', () => {
        expect(navClass).toBe('mt-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2');
        expect(spanClass).toBe('order-first w-full min-w-0 text-center text-xs text-gray-400 sm:order-none sm:w-auto');
        expect(btnClass).toContain('min-h-11');
    });

    test('320px: nada cruza el borde derecho; botones a 44px', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const { context, page: f } = await isolatedFixture(browser, css, 320, pager(navClass ?? '', spanClass ?? ''));
        try {
            const m = await f.evaluate(() => {
                const r = (sel: string) => (document.querySelector(sel) as HTMLElement).getBoundingClientRect();
                const prev = r('[data-testid="prev"]');
                const next = r('[data-testid="next"]');
                const info = r('[data-testid="info"]');
                return {
                    sw: document.documentElement.scrollWidth,
                    prevRight: Math.round(prev.right), nextRight: Math.round(next.right), infoRight: Math.round(info.right),
                    prevH: Math.round(prev.height), nextH: Math.round(next.height),
                    nextTop: Math.round(next.top), prevTop: Math.round(prev.top), infoTop: Math.round(info.top),
                };
            });
            expect(m.sw, 'documento sin overflow').toBeLessThanOrEqual(320);
            expect(m.prevRight, 'Anterior dentro').toBeLessThanOrEqual(320);
            expect(m.nextRight, 'Siguiente dentro').toBeLessThanOrEqual(320);
            expect(m.infoRight, 'texto dentro').toBeLessThanOrEqual(320);
            expect(m.prevH, 'Anterior >=44px').toBeGreaterThanOrEqual(44);
            expect(m.nextH, 'Siguiente >=44px').toBeGreaterThanOrEqual(44);
            expect(m.infoTop, 'el texto va en su propia línea (encima de los botones)').toBeLessThan(m.prevTop);
            expect(m.prevTop, 'los dos botones comparten línea').toBe(m.nextTop);
        } finally {
            await context.close();
        }
    });

    test('768px: fila única de siempre (sm devuelve el orden)', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const { context, page: f } = await isolatedFixture(browser, css, 768, pager(navClass ?? '', spanClass ?? ''));
        try {
            const m = await f.evaluate(() => {
                const r = (sel: string) => (document.querySelector(sel) as HTMLElement).getBoundingClientRect();
                return { prevTop: Math.round(r('[data-testid="prev"]').top), infoTop: Math.round(r('[data-testid="info"]').top), nextTop: Math.round(r('[data-testid="next"]').top) };
            });
            expect(Math.abs(m.prevTop - m.infoTop), 'texto y botones en la misma fila').toBeLessThan(12);
            expect(Math.abs(m.prevTop - m.nextTop), 'fila única').toBeLessThan(12);
        } finally {
            await context.close();
        }
    });

    test('control: la fila antigua desborda a 320px (documento aparte)', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const { context, page: f } = await isolatedFixture(browser, css, 320, pager(OLD_NAV, OLD_SPAN));
        try {
            const m = await f.evaluate(() => {
                const next = (document.querySelector('[data-testid="next"]') as HTMLElement).getBoundingClientRect();
                return { sw: document.documentElement.scrollWidth, nextRight: Math.round(next.right) };
            });
            expect(m.nextRight, 'control: «Siguiente» se salía por la derecha').toBeGreaterThan(320);
        } finally {
            await context.close();
        }
    });
});
