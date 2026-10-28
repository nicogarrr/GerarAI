/**
 * Lighthouse CI de las pantallas clave (.github/workflows/a11y-perf.yml, manual
 * y nocturno, no bloquea). La cookie la crea scripts/lhci/session.mjs.
 *
 * Presupuesto:
 * - error: heading-order en /portfolio y /taxes (arreglado en #2676) no vuelve;
 * - aviso: nota de accesibilidad < 0,95, CLS > 0,1, LCP > 4 s, TBT > 300 ms e
 *   imágenes sobredimensionadas (los logos de #2675).
 * Los informes se suben como artefacto (target filesystem), no a un servidor.
 */
const base = process.env.LHCI_BASE_URL ?? 'http://127.0.0.1:3000';
const cookie = process.env.LHCI_COOKIE;
if (!cookie) throw new Error('Falta LHCI_COOKIE (node scripts/lhci/session.mjs)');

const PAGES = ['/inicio', '/watchlist', '/research/MSFT', '/portfolio', '/taxes', '/research/assistant'];

module.exports = {
    ci: {
        collect: {
            url: PAGES.map((p) => `${base}${p}`),
            numberOfRuns: 1,
            settings: {
                chromeFlags: '--no-sandbox --headless=new',
                extraHeaders: JSON.stringify({ Cookie: cookie }),
                onlyCategories: ['performance', 'accessibility', 'best-practices'],
            },
        },
        assert: {
            assertMatrix: [
                {
                    matchingUrlPattern: '.*',
                    assertions: {
                        'categories:accessibility': ['warn', { minScore: 0.95 }],
                        'cumulative-layout-shift': ['warn', { maxNumericValue: 0.1 }],
                        'largest-contentful-paint': ['warn', { maxNumericValue: 4000 }],
                        'total-blocking-time': ['warn', { maxNumericValue: 300 }],
                        'uses-responsive-images': ['warn', { maxLength: 0 }],
                    },
                },
                {
                    matchingUrlPattern: '/(portfolio|taxes)$',
                    assertions: { 'heading-order': 'error' },
                },
            ],
        },
        upload: { target: 'filesystem', outputDir: '.lighthouseci/reports' },
    },
};
