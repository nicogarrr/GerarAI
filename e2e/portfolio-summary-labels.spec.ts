import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type Page } from '@playwright/test';
test.skip(process.env.E2E_UI_RUN !== '1', 'Local UI fixture required');

// Regresión P23 v2 (18-nov-2026): la etiqueta «Ganancia/Pérdida» de
// PortfolioSummary computaba 11px en <sm. v1 la subió a 12px pero el Auditor
// la encontró RECORTADA (captura 18-nov): en 2 columnas a 320px la caja de
// contenido son ~104px y el token irrompible «GANANCIA/PÉRDIDA» mide 145px a
// 12px tracking-wider; overflow-hidden ocultaba el final. Medir altura y el
// scrollWidth del documento no detecta ese recorte (lección v1).
// v2: grid-cols-1 hasta 420px (breakpoint ya usado por los valores) y las
// cuatro etiquetas idénticas a text-xs uppercase tracking-wider.
// Medida correcta: scrollWidth <= clientWidth DE LA ETIQUETA, con control en
// documento aparte que reproduce el recorte de v1 a los mismos 12px.
//
// Fixture aislada con el CSS real de la app; clases extraídas del fuente.

const summarySrc = readFileSync('components/portfolio/PortfolioSummary.tsx', 'utf8');

const labelClasses = [...summarySrc.matchAll(/<p className="([^"]+)">\{ti\('portfolio\.summary\.(?:totalValue|costTitle|gainTitle|returnTitle)'\)\}<\/p>/g)]
    .map(match => match[1]);
const gridClass = summarySrc.match(/<div className="(grid grid-cols-[^"]+)">/)?.[1];

const OLD_GAIN_11 = 'text-gray-400 text-[11px] sm:text-xs uppercase tracking-normal sm:tracking-wider font-semibold mb-1';
const V1_GAIN_12 = 'text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1';
const V1_GRID = 'grid grid-cols-2 gap-3 sm:gap-4 sm:[grid-template-columns:repeat(auto-fit,minmax(12rem,1fr))]';

// Fiel al producto: tarjetas rounded-xl p-4 relative overflow-hidden con
// etiqueta + valor en negrita. Textos reales de lib/i18n/messages/es.
function card(labelCls: string, label: string, value: string, pfx: string): string {
    return `<div class="bg-[#111111] border border-gray-800 rounded-xl p-4 sm:p-5 relative overflow-hidden">
        <p data-testid="${pfx}-label" class="${labelCls}">${label}</p>
        <p data-testid="${pfx}-value" class="text-base min-[420px]:text-lg sm:text-2xl font-bold tracking-tight break-words text-gray-100">${value}</p>
    </div>`;
}

function grid(gridCls: string, labelCls: (i: number) => string, pfx: string): string {
    const items: [string, string][] = [
        ['Valor total (neto)', '12.345,67 €'],
        ['Coste de las posiciones', '10.000,00 €'],
        ['Ganancia/Pérdida', '+2.345,67 €'],
        ['Rendimiento', '+23,46 %'],
    ];
    return `<div class="${gridCls}">
        ${items.map(([label, value], i) => card(labelCls(i), label, value, `${pfx}-${i}`)).join('')}
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

async function isolatedFixture(browser: Browser, css: string, width: number, body: string) {
    const context = await browser.newContext({ viewport: { width, height: 568 }, javaScriptEnabled: false });
    const page = await context.newPage();
    await page.setContent(`<style>${css}</style><main class="bg-gray-950 p-4 text-gray-200">${body}</main>`);
    return { context, page };
}

function measureLabels() {
    const labels = [...document.querySelectorAll('[data-testid$="-label"]')] as HTMLElement[];
    const values = [...document.querySelectorAll('[data-testid$="-value"]')] as HTMLElement[];
    return {
        sizes: labels.map(el => getComputedStyle(el).fontSize),
        // Recorte horizontal dentro de la tarjeta (overflow-hidden): scrollWidth
        // del texto contra clientWidth de su caja. La lección de v1: medir la
        // altura o el scrollWidth del documento NO detecta este recorte.
        clips: labels.map(el => el.scrollWidth - el.clientWidth),
        labelHeights: labels.map(el => Math.round(el.getBoundingClientRect().height)),
        valueHeights: values.map(el => Math.round(el.getBoundingClientRect().height)),
        sw: document.documentElement.scrollWidth,
    };
}

test.describe('P23 v2: resumen de /portfolio a 1 columna <420px, etiquetas a 12px sin recorte', () => {
    test('las clases fuente son las parcheadas (grid y etiquetas)', () => {
        expect(gridClass, 'grid 1 columna hasta 420px').toBe('grid grid-cols-1 min-[420px]:grid-cols-2 gap-3 sm:gap-4 sm:[grid-template-columns:repeat(auto-fit,minmax(12rem,1fr))]');
        expect(labelClasses.length, 'cuatro etiquetas resumen').toBe(4);
        for (const classes of labelClasses) {
            expect(classes).toBe(V1_GAIN_12);
        }
        expect(summarySrc).not.toContain('text-[11px]');
    });

    test('320px: 12px computados, etiqueta sin recorte (scrollWidth<=clientWidth), una línea', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const { context, page: f } = await isolatedFixture(browser, css, 320, grid(gridClass ?? '', () => labelClasses[2] ?? '', 'n'));
        try {
            const m = await f.evaluate(measureLabels);
            expect(m.sizes).toEqual(['12px', '12px', '12px', '12px']);
            expect(Math.max(...m.clips), 'ninguna etiqueta recortada por overflow-hidden').toBeLessThanOrEqual(0);
            expect(Math.max(...m.labelHeights), 'las cuatro etiquetas en una línea').toBeLessThanOrEqual(20);
            expect(Math.max(...m.valueHeights), 'los valores no envuelven').toBeLessThanOrEqual(30);
            expect(m.sw, 'sin overflow horizontal del documento').toBeLessThanOrEqual(320);
        } finally {
            await context.close();
        }
    });

    test('420px: vuelve a 2 columnas y «Ganancia/Pérdida» sigue sin recorte', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const { context, page: f } = await isolatedFixture(browser, css, 420, grid(gridClass ?? '', () => labelClasses[2] ?? '', 'w'));
        try {
            const m = await f.evaluate(measureLabels);
            const cards = await f.evaluate(() => (document.querySelector('[data-testid="w-0-label"]') as HTMLElement).getBoundingClientRect().width);
            expect(cards, 'a 420px hay 2 columnas (etiqueta < mitad del viewport)').toBeLessThan(210);
            expect(m.sizes).toEqual(['12px', '12px', '12px', '12px']);
            expect(Math.max(...m.clips), 'sin recorte en 2 columnas a 420px').toBeLessThanOrEqual(0);
        } finally {
            await context.close();
        }
    });

    test('control: v1 (12px + 2 columnas) recorta 145>104; 11px computa 11px (documento aparte)', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const labels = ['text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1', 'text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1', OLD_GAIN_11, 'text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1'];
        // La combinación exacta de v1 (12px tracking-wider + 2 columnas):
        // el recorte que midió el Auditor a 320px.
        const { context, page: f } = await isolatedFixture(browser, css, 320, `<div class="${V1_GRID}">${card(V1_GAIN_12, 'Ganancia/Pérdida', '+2.345,67 €', 'v1x')}</div>`);
        try {
            const v1 = await f.evaluate(() => {
                const el = document.querySelector('[data-testid="v1x-label"]') as HTMLElement;
                return { size: getComputedStyle(el).fontSize, clip: el.scrollWidth - el.clientWidth };
            });
            expect(v1.size, 'control: v1 ya estaba a 12px').toBe('12px');
            expect(v1.clip, 'control: v1 recortaba la etiqueta (scrollWidth>clientWidth)').toBeGreaterThan(0);
        } finally {
            await context.close();
        }
        const c2 = await isolatedFixture(browser, css, 320, grid(V1_GRID, i => labels[i], 'v'));
        try {
            const old = await c2.page.evaluate(() => {
                const el = document.querySelector('[data-testid="v-2-label"]') as HTMLElement;
                return getComputedStyle(el).fontSize;
            });
            expect(old, 'control: la etiqueta original computaba 11px').toBe('11px');
        } finally {
            await c2.context.close();
        }
    });
});
