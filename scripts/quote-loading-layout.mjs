// Run: npm run test:quote-layout (requires the Browser E2E Chromium install)
// Real component + real app CSS, deterministic delayed quote, no app server.
import { build } from 'vite';
import tailwindcss from '@tailwindcss/postcss';
import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const out = process.env.QUOTE_LAYOUT_ARTIFACTS ?? '/tmp/quote-loading-layout';
await mkdir(out, { recursive: true });
const bundle = await build({
    configFile: false, root, logLevel: 'warn',
    resolve: { alias: { '@': root } },
    css: { postcss: { plugins: [tailwindcss()] } },
    plugins: [{
        name: 'quote-layout-test-boundaries', enforce: 'pre',
        resolveId(id, importer) {
            if (id === '@/lib/i18n/client' || /\/lib\/i18n\/client(?:\.[jt]sx?)?$/.test(id)) return '\0quote-i18n';
            if (id.includes('CompanyTechnicalWorkspace') && importer?.includes('CompanyHeaderQuote')) return '\0quote-chart';
        },
        load(id) {
            if (id === '\0quote-i18n') return `import { createFormatters } from '@/lib/format';
                const fmt = createFormatters('es'); const t = key => ({ 'research.headerQuote.liveUnavailable': 'Cotización en vivo no disponible', 'research.headerQuote.open': 'Apertura', 'research.headerQuote.high': 'Máximo', 'research.headerQuote.low': 'Mínimo', 'research.headerQuote.previousClose': 'Cierre anterior' }[key] ?? key);
                export const useFormat = () => fmt; export const useLocale = () => 'es'; export const useT = () => t;`;
            if (id === '\0quote-chart') return 'export const CompanyTechnicalWorkspace = () => null;';
        },
    }],
    build: { write: false, minify: false, rollupOptions: { input: path.join(root, 'tests/browser/fixtures/quote-layout.tsx') } },
});
const outputs = bundle.output;
const js = outputs.find(item => item.type === 'chunk' && item.isEntry).code;
const css = outputs.filter(item => item.type === 'asset' && item.fileName.endsWith('.css')).map(item => item.source).join('\n');
const server = createServer((req, res) => {
    res.setHeader('Content-Type', req.url === '/bundle.js' ? 'text/javascript' : req.url === '/style.css' ? 'text/css' : 'text/html');
    res.end(req.url === '/bundle.js' ? js : req.url === '/style.css' ? css : '<!doctype html><html class="dark"><head><link rel="stylesheet" href="/style.css"></head><body><div id="root"></div><script type="module" src="/bundle.js"></script></body></html>');
}).listen(0, '127.0.0.1');
await new Promise(resolve => server.once('listening', resolve));
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH, args: ['--no-sandbox'] } : {}) });
const measurements = [];
try {
    for (const width of [390, 1440]) for (const compact of [true, false]) for (const state of ['regular', 'negative', 'flat', 'closed', 'unavailable', 'delayed']) {
        const page = await browser.newPage({ viewport: { width, height: 900 } });
        const errors = [];
        page.on('pageerror', error => { errors.push(error.message); console.error('PAGE ERROR', error.message); });
        await page.goto(`http://127.0.0.1:${server.address().port}/?compact=${compact ? 1 : 0}`);
        await page.waitForFunction(() => typeof window.resolveQuote === 'function');
        const measure = () => page.evaluate(() => {
            const quote = document.querySelector('[data-testid="company-header-quote"]');
            const link = document.querySelector('[data-testid="report-link"]');
            return { quoteHeight: quote.getBoundingClientRect().height, linkY: link.getBoundingClientRect().top, overflow: document.documentElement.scrollWidth > innerWidth };
        });
        const before = await measure();
        const name = `${width}-${compact ? 'compact' : 'full'}${state === 'regular' ? '' : '-' + state}`;
        if (state === 'regular') await page.screenshot({ path: path.join(out, `${name}-loading.png`), fullPage: true });
        await page.evaluate((state) => window.resolveQuote({
            ticker: 'MSFT', fetched_at: 1788966000, source: 'fixture', status: 'available', price: 336.56, currency: 'USD',
            timestamp: 1788966000, price_session: 'regular', session: 'regular', change: 2.34, change_percent: 0.70,
            ...(state === 'negative' ? { change: -2.34, change_percent: -0.70 } : {}),
            ...(state === 'flat' ? { change: 0, change_percent: 0 } : {}),
            ...(state === 'closed' ? { session: 'cerrado', close_change: 2.34, close_change_percent: 0.70, close_change_date: '2026-09-08', close_change_previous_date: '2026-09-07' } : {}),
            ...(state === 'unavailable' ? { status: 'unavailable', price: null } : {}),
            ...(state === 'delayed' ? { status: 'retrasado' } : {}),
        }), state);
        await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'));
        const after = await measure();
        if (state === 'regular') await page.screenshot({ path: path.join(out, `${name}-loaded.png`), fullPage: true });
        measurements.push({ name, before, after, errors });
        await page.close();
    }
    console.log(JSON.stringify(measurements, null, 2));
    for (const { name, before, after, errors } of measurements) {
        assert.deepEqual(errors, []);
        assert.equal(after.overflow, false);
        assert.equal(after.quoteHeight, before.quoteHeight, `${name}: quote height changed`);
        assert.equal(after.linkY, before.linkY, `${name}: content below the quote moved`);
    }
    console.log('PASS 390/1440 × compact/full × six quote states: stable quote and link with real app CSS');
} finally {
    await writeFile(path.join(out, 'measurements.json'), JSON.stringify(measurements, null, 2));
    await browser.close(); server.close();
}
