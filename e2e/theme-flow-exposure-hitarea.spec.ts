import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type Page } from '@playwright/test';
test.skip(process.env.E2E_UI_RUN !== '1', 'Local UI fixture required');

// Regresión P20 v2 (Auditoría 18-nov-2026): los tickers de «tu exposición»
// del flujo de /temas van seguidos (coma + espacio ≈ 5-8 px). La primera
// versión usaba pseudo-expansión horizontal (before:-inset-x-1.5) y los
// halos de destinos distintos se solapaban 5,33 px (medido por Auditoría en
// Chrome con 3 tickers); y con expansión solo vertical el halo de la línea
// de arriba capturaba los huecos de la de abajo al envolver (paso 16 px).
//
// Solución: SIN pseudo-elemento. Cada ticker es un chip real min-h-11
// min-w-11 (44 px), el patrón ya aprobado de HoldingsLines en la misma
// página (app/(root)/temas/page.tsx). Cajas reales contiguas: nada solapa.
//
// Este spec no se fía de las clases: extrae la clase real del fuente,
// monta una línea con 8 tickers que ENVUELVE en un contenedor estrecho y
// hit-testea en navegador los huecos y los wraps. Incluye una línea de
// control con la clase antigua que DEBE fallar: si no discrimina, no vale.

const source = readFileSync('app/(root)/temas/_components/ThemeFlow.tsx', 'utf8');
const exposureClass = source.match(/className="(inline-flex min-h-11[^"]*text-teal-300[^"]*)"/)?.[1];
// El separador «, » vive FUERA del enlace (texto del <span> envolvente):
// si alguien lo mete dentro, el hueco desaparece y la línea se rompe.
const separatorOutsideLink = />\s*\{index > 0 \? ', ' : ''\}\s*<Link/.test(source);
const oldClass = 'relative font-semibold text-teal-300 before:absolute before:-inset-x-1.5 before:-inset-y-2 before:content-[\'\'] hover:text-teal-200';

const TICKERS = ['NVDA', 'MSFT', 'AAPL', 'GOOGL', 'AMZN', 'AVGO', 'ORCL', 'TSM'];

function line(cls: string, idPrefix: string): string {
    return TICKERS.map((t, i) =>
        `<span>${i > 0 ? ', ' : ''}<a data-testid="${idPrefix}-${t}" class="${cls}" href="/research/${t}">${t}</a></span>`,
    ).join('');
}

async function realAppCss(page: Page): Promise<string> {
    await page.goto('/temas', { waitUntil: 'domcontentloaded' });
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
    await page.setContent(`<style>${css}</style><main class="bg-gray-950 p-4 text-gray-200">
        <p data-testid="linea-nueva" class="w-56 rounded-lg border border-teal-400/25 bg-teal-400/10 px-3 py-2 text-xs text-gray-200">
            <span class="font-semibold text-gray-100">Tu exposición</span> En cartera: ${line(exposureClass ?? '', 'n')}
        </p>
        <p data-testid="linea-vieja" class="mt-4 w-56 rounded-lg border border-teal-400/25 bg-teal-400/10 px-3 py-2 text-xs text-gray-200">
            <span class="font-semibold text-gray-100">Tu exposición</span> En cartera: ${line(oldClass, 'v')}
        </p>
    </main>`);
    return { context, page };
}

type Geom = {
    lines: number;
    boxHeights: number[];
    gaps: { pair: string; gap: number; hit: string | null }[];
    wrapHit: string | null;
    lineOverlap: number;
};

async function measure(page: Page, prefix: 'n' | 'v'): Promise<Geom> {
    return page.evaluate((pfx) => {
        const links = Array.from(document.querySelectorAll<HTMLAnchorElement>(`a[data-testid^="${pfx}-"]`));
        const rects = links.map(a => ({ a, r: a.getBoundingClientRect() }));
        const lines = new Set(rects.map(({ r }) => Math.round(r.top))).size;
        const boxHeights = rects.map(({ r }) => Math.round(r.height));
        const gaps: { pair: string; gap: number; hit: string | null }[] = [];
        for (let i = 0; i + 1 < rects.length; i++) {
            const A = rects[i], B = rects[i + 1];
            if (Math.abs(A.r.top - B.r.top) >= 2) continue;
            const gap = B.r.left - (A.r.left + A.r.width);
            const el = document.elementFromPoint(A.r.left + A.r.width + gap / 2, A.r.top + A.r.height / 2);
            gaps.push({ pair: `${A.a.textContent}->${B.a.textContent}`, gap: Math.round(gap * 100) / 100, hit: el?.closest('a')?.getAttribute('data-testid') ?? null });
        }
        // Wrap: el primer enlace de la segunda línea se acierta en su centro,
        // y las cajas de líneas adyacentes NO se solapan verticalmente.
        const firstTop = Math.round(rects[0].r.top);
        const secondLine = rects.find(({ r }) => Math.round(r.top) > firstTop + 2);
        let wrapHit: string | null = null;
        let lineOverlap = 0;
        if (secondLine) {
            const el = document.elementFromPoint(secondLine.r.left + secondLine.r.width / 2, secondLine.r.top + secondLine.r.height / 2);
            wrapHit = el?.closest('a')?.getAttribute('data-testid') ?? null;
            const above = rects.filter(({ r }) => Math.round(r.top) === firstTop);
            for (const A of above) {
                const xOverlap = Math.min(A.r.right, secondLine.r.right) - Math.max(A.r.left, secondLine.r.left);
                if (xOverlap > 0) lineOverlap = Math.max(lineOverlap, A.r.bottom - secondLine.r.top);
            }
        }
        return { lines, boxHeights, gaps, wrapHit, lineOverlap };
    }, prefix);
}

for (const width of [320, 390]) {
    test(`exposición de /temas: chips de 44 px sin solape horizontal ni de wrap a ${width}px`, async ({ page, browser }) => {
        expect(exposureClass, 'clase chip extraída de ThemeFlow.tsx').toBeTruthy();
        expect(exposureClass).not.toContain('before:');
        expect(separatorOutsideLink, 'el separador «, » vive fuera del enlace').toBe(true);
        const css = await realAppCss(page);
        const { context, page: fixture } = await isolatedFixture(browser, css, width);
        try {
            const nuevo = await measure(fixture, 'n');
            // Cajas reales de 44 px (2+ tickers, y la línea envuelve)…
            expect(Math.min(...nuevo.boxHeights)).toBeGreaterThanOrEqual(44);
            expect(nuevo.lines).toBeGreaterThanOrEqual(2);
            // …huecos entre tickers de la misma línea NO clicables…
            expect(nuevo.gaps.length).toBeGreaterThanOrEqual(2);
            for (const g of nuevo.gaps) expect(g.hit, `hueco ${g.pair} (${g.gap}px)`).toBeNull();
            // …wrap: el enlace de la 2.ª línea se acierta y las líneas no se solapan.
            expect(nuevo.wrapHit).toBeTruthy();
            expect(nuevo.lineOverlap, 'solape vertical entre líneas').toBeLessThanOrEqual(0.5);

            // Control: con la clase ANTIGUA (-inset-x-1.5) los huecos sí son
            // clicables: el test discrimina la regresión, no es un pase vacío.
            const viejo = await measure(fixture, 'v');
            expect(viejo.gaps.some(g => g.hit !== null), 'control: la clase antigua sí solapa (test no vacío)').toBe(true);
        } finally {
            await context.close();
        }
    });
}
