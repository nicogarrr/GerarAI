import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type Page } from '@playwright/test';
test.skip(process.env.E2E_UI_RUN !== '1', 'Local UI fixture required');

// Regresión P22 (18-nov-2026, medido en prod a 320px):
//  - /research/AAPL (PriceEventsPanel): botón de fecha 16px, toggle «Detalle»
//    ~13px. El enlace de fuente de la misma fila ya llevaba el patrón
//    aprobado (min-h-11 real + sm:min-h-0); se extiende a ambos botones.
//  - /insider (InsiderSignalsView): ticker del título 22px (inline aislado →
//    pseudo before:-inset) y enlace SEC «Ver filing» ~16px (min-h-11 real),
//    en las DOS instancias (señales y filings).
//
// Fixture aislada con el CSS real de la app; las clases se extraen del
// fuente. Control con las clases antiguas en DOCUMENTO APARTE (lección P21:
// scrollWidth/geometry son del documento; nunca mezclar control y caso).

const panelSrc = readFileSync('components/research/PriceEventsPanel.tsx', 'utf8');
const signalsSrc = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');

const dateBtnClass = panelSrc.match(/<button type="button" onClick=\{\(\) => onFocus\(event\.date\)\} className="([^"]+)"/)?.[1];
// [^>] no vale: el onClick lleva flechas `=>` (con `>`). No codicioso hasta SU className.
const detailBtnClass = panelSrc.match(/aria-expanded=\{open === event\.id\}[\s\S]*?className="([^"]+)"/)?.[1];
const titleLinkClass = signalsSrc.match(/<Link\s+href=\{`\/research\/\$\{encodeURIComponent\(initialTicker\)\}`\}\s+className="([^"]+)"/)?.[1];
const secNew = 'inline-flex min-h-11 items-center gap-1 text-xs text-teal-300 hover:text-teal-200 hover:underline sm:min-h-0';
const secCount = signalsSrc.split(secNew).length - 1;

const OLD = {
    date: 'tabular-nums text-gray-400 underline-offset-2 hover:underline',
    detail: 'text-xs text-gray-500 hover:text-gray-200',
    title: 'font-mono text-teal-300 hover:text-teal-200 hover:underline',
    sec: 'inline-flex items-center gap-1 text-xs text-teal-300 hover:text-teal-200 hover:underline',
};

function panelRow(dateCls: string, detailCls: string, pfx: string): string {
    return `<li class="rounded-md border border-gray-800 px-2 py-1.5 text-xs">
        <div class="flex flex-wrap items-baseline gap-2">
            <button data-testid="${pfx}-fecha" type="button" class="${dateCls}">12 nov 2025</button>
            <span class="rounded px-1 text-xs font-semibold">Resultados</span>
            <span class="min-w-0 flex-1 basis-full text-gray-200 sm:basis-auto">Publica resultados del trimestre</span>
            <a class="inline-flex min-h-11 min-w-11 items-center text-xs text-gray-500 underline sm:min-h-0 sm:min-w-0" href="#fuente">Fuente</a>
            <button data-testid="${pfx}-detalle" type="button" class="${detailCls}">Detalle</button>
        </div>
    </li>`;
}

function insiderBits(titleCls: string, secCls: string, pfx: string): string {
    // Fiel al producto: el título lleva «· » como texto (nada de expresiones JSX
    // en HTML crudo — Auditoría P22 v1: la fixture imprimía "{' '}" literal).
    // Y se montan las DOS instancias del enlace SEC (señales + filings): el
    // conteo de fuente no sustituye montarlas (Auditoría P22 v1).
    return `<div class="space-y-1.5 p-6 flex flex-col gap-3 border-b border-gray-700/50 pb-4">
        <h2 class="tracking-tight text-lg font-semibold text-gray-100">Señales insider ·
            <a data-testid="${pfx}-titulo" class="${titleCls}" href="/research/DASH">DASH</a>
        </h2>
        <p class="mt-0.5 text-sm text-gray-500">3 señales · 2 compras</p>
    </div>
    <div class="p-3"><span class="mt-1 flex flex-wrap items-center gap-2">
        <span class="rounded px-1.5 py-0.5 text-xs font-bold uppercase bg-teal-400/15 text-teal-300">Form 4</span>
        <a data-testid="${pfx}-sec-senal" class="${secCls}" href="#sec1">Ver filing SEC</a>
    </span></div>
    <ul class="space-y-2"><li class="rounded-lg border border-gray-800 p-3 text-sm">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span class="rounded px-1.5 py-0.5 text-xs font-bold uppercase bg-teal-400/15 text-teal-300">Form 4/A</span>
            <span class="font-mono text-gray-300">18 nov 2026</span>
            <a data-testid="${pfx}-sec-filing" class="${secCls}" href="#sec2">Ver filing SEC</a>
        </div>
    </li></ul>`;
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

test.describe('P22: zonas táctiles 44px en /research/AAPL e /insider', () => {
    test('las clases fuente son las parcheadas (y las DOS instancias SEC)', () => {
        expect(dateBtnClass, 'botón de fecha').toContain('min-h-11');
        expect(detailBtnClass, 'toggle Detalle').toContain('min-h-11');
        expect(titleLinkClass, 'ticker del título').toContain('before:-inset-y-3.5');
        expect(secCount, 'enlaces SEC con min-h-11 (señales + filings)').toBe(2);
    });

    test('320px: fecha, Detalle y SEC miden >=44px; el pseudo del título hit-testea', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const body = `<ol class="max-h-80 space-y-1">${panelRow(dateBtnClass ?? '', detailBtnClass ?? '', 'n')}</ol>${insiderBits(titleLinkClass ?? '', secNew, 'n')}`;
        const { context, page: f } = await isolatedFixture(browser, css, 320, body);
        try {
            const m = await f.evaluate(() => {
                const h = (sel: string) => Math.round((document.querySelector(sel) as HTMLElement).getBoundingClientRect().height);
                const titulo = document.querySelector('[data-testid="n-titulo"]') as HTMLElement;
                const r = titulo.getBoundingClientRect();
                // Barrido de 1px: MIDE el tramo contiguo alrededor del enlace donde
                // elementFromPoint resuelve al enlace (su pseudo ::before cuenta).
                // Dos puntos no prueban el tamaño efectivo (Auditoría P22 v1:
                // ±6px capturaba pero el área real era 36px <44).
                const cx = r.left + r.width / 2;
                const hit = (y: number) => {
                    const el = document.elementFromPoint(cx, y);
                    return el === titulo || titulo.contains(el);
                };
                let top = r.top;
                while (top > r.top - 30 && hit(top - 1)) top -= 1;
                let bottom = r.bottom;
                while (bottom < r.bottom + 30 && hit(bottom + 1)) bottom += 1;
                return {
                    fecha: h('[data-testid="n-fecha"]'),
                    detalle: h('[data-testid="n-detalle"]'),
                    secSenal: h('[data-testid="n-sec-senal"]'),
                    secFiling: h('[data-testid="n-sec-filing"]'),
                    tituloAlto: Math.round(r.height),
                    tituloEfectivo: Math.round((bottom - top) * 10) / 10,
                };
            });
            expect(m.fecha, 'fecha >=44px a 320px').toBeGreaterThanOrEqual(44);
            expect(m.detalle, 'Detalle >=44px a 320px').toBeGreaterThanOrEqual(44);
            expect(m.secSenal, 'SEC (señales) >=44px a 320px').toBeGreaterThanOrEqual(44);
            expect(m.secFiling, 'SEC (filings) >=44px a 320px').toBeGreaterThanOrEqual(44);
            expect(m.tituloEfectivo, 'área efectiva del ticker del título >=44px (barrido)').toBeGreaterThanOrEqual(44);
        } finally {
            await context.close();
        }
    });

    test('768px: sm:min-h-0 devuelve el ritmo denso (sin 44px forzado)', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const body = `<ol class="max-h-80 space-y-1">${panelRow(dateBtnClass ?? '', detailBtnClass ?? '', 'n')}</ol>${insiderBits(titleLinkClass ?? '', secNew, 'n')}`;
        const { context, page: f } = await isolatedFixture(browser, css, 768, body);
        try {
            const m = await f.evaluate(() => {
                const h = (sel: string) => Math.round((document.querySelector(sel) as HTMLElement).getBoundingClientRect().height);
                return { fecha: h('[data-testid="n-fecha"]'), detalle: h('[data-testid="n-detalle"]'), secSenal: h('[data-testid="n-sec-senal"]'), secFiling: h('[data-testid="n-sec-filing"]') };
            });
            expect(m.fecha, 'fecha vuelve al ritmo denso en escritorio').toBeLessThan(30);
            expect(m.detalle, 'Detalle vuelve al ritmo denso en escritorio').toBeLessThan(30);
            expect(m.secSenal, 'SEC (señales) vuelve al ritmo denso').toBeLessThan(30);
            expect(m.secFiling, 'SEC (filings) vuelve al ritmo denso').toBeLessThan(30);
        } finally {
            await context.close();
        }
    });

    test('control: las clases antiguas miden <24px (documento aparte)', async ({ browser, page }) => {
        const css = await realAppCss(page);
        const body = `<ol class="max-h-80 space-y-1">${panelRow(OLD.date, OLD.detail, 'v')}</ol>${insiderBits(OLD.title, OLD.sec, 'v')}`;
        const { context, page: f } = await isolatedFixture(browser, css, 320, body);
        try {
            const m = await f.evaluate(() => {
                const h = (sel: string) => Math.round((document.querySelector(sel) as HTMLElement).getBoundingClientRect().height);
                const titulo = document.querySelector('[data-testid="v-titulo"]') as HTMLElement;
                const r = titulo.getBoundingClientRect();
                const cx = r.left + r.width / 2;
                const hit = (y: number) => {
                    const el = document.elementFromPoint(cx, y);
                    return el === titulo || titulo.contains(el);
                };
                let top = r.top;
                while (top > r.top - 30 && hit(top - 1)) top -= 1;
                let bottom = r.bottom;
                while (bottom < r.bottom + 30 && hit(bottom + 1)) bottom += 1;
                return {
                    fecha: h('[data-testid="v-fecha"]'),
                    detalle: h('[data-testid="v-detalle"]'),
                    secSenal: h('[data-testid="v-sec-senal"]'),
                    secFiling: h('[data-testid="v-sec-filing"]'),
                    tituloEfectivo: Math.round((bottom - top) * 10) / 10,
                };
            });
            expect(m.fecha, 'control: fecha vieja <24px').toBeLessThan(24);
            expect(m.detalle, 'control: Detalle viejo <24px').toBeLessThan(24);
            expect(m.secSenal, 'control: SEC viejo (señales) <24px').toBeLessThan(24);
            expect(m.secFiling, 'control: SEC viejo (filings) <24px').toBeLessThan(24);
            expect(m.tituloEfectivo, 'control: sin pseudo el área efectiva es la caja (~20px <44)').toBeLessThan(24);
        } finally {
            await context.close();
        }
    });
});
