# Public font delivery benchmark

Measured 2026-10-16, Europe/Madrid. Baseline commit: `8b4f374d3acfd941afb165821f0186dbbf1193d5`.

## Method

Two isolated production builds of the same Next.js source/dependencies, running on the same VM with an empty temporary MongoDB. No production database, accounts or API keys. Base uses the existing TTF files with both fonts preloaded. Candidate uses lossless WOFF2 containers and disables preload only for Instrument Serif. Browser discovers that font through the actual landing heading; auth does not use it.

Chromium, 390x900 viewport, CPU slowdown 4x, emulated 1.6 Mbps download and 150ms latency. Three cold-browser-cache samples per route/build, alternating the build order. Largest Contentful Paint from PerformanceObserver. These are not Lighthouse scores, forced server cold starts, or measurements of the deployed candidate on Vercel. Request handling/TTFB varies; do not attribute all timing changes to fonts.

| Route | Build | Font transfer bytes | JS transfer bytes | Subresource transfer bytes | Median TTFB ms | Median LCP ms |
|---|---|---:|---:|---:|---:|---:|
| / | base | 106359 | 160486 | 310783 | 66 | 1290 |
| / | candidate | 81764 | 160486 | 286180 | 44 | 1252 |
| /sign-in | base | 106359 | 180851 | 320623 | 44 | 1314 |
| /sign-in | candidate | 54084 | 180854 | 268345 | 20 | 1137 |

The reliable effect is fewer font bytes: -24595 bytes (-23.1%) on landing, -52275 bytes (-49.2%) on login. Login no longer requests Instrument Serif. JS is unchanged within a few bytes. The small timing sample is directionally favorable in this run, not evidence of a guaranteed LCP or TTFB gain.

A first rejected candidate only split the font module and still preloaded Serif on login. The new browser test caught it. A separate run for that rejected candidate did not establish a LCP benefit. It is not mixed with the table above.

## Fidelity and tests

WOFF2 was made from the same bundled TTF files. Decoded glyph order, cmap, horizontal metrics, and every glyph's coordinates/contours/flags match. WOFF2 can re-encode glyf bytes; no byte-identical binary claim. Existing OFL/copyright notices are preserved.

Production candidate: build exit 0; ESLint exit 0; 12/12 browser tests: 10 responsive header widths and two font-loading tests. Real FontFace family/status loaded is checked. Login must not request or load Instrument Serif. Screenshots inspected at 390px for landing and login; no layout/typography changes seen. This does not certify private authenticated pages.

## Public baseline, not before/after

Earlier on the live alias el alias de producción en Vercel (2026-10-16 09:28-09:30 CEST), three cold/warm browser-cache samples per route, viewport390x844 with the same CPU/network settings:

| Route | Cold TTFB ms | Cold LCP ms | Cold JS bytes | Warm TTFB ms | Warm LCP ms |
|---|---:|---:|---:|---:|---:|
| / | 367 | 1694 | 164891 | 88 | 479 |
| /sign-in | 154 | 1570 | 186258 | 72 | 332 |
| /metodologia | 159 | 1734 | 195859 | 105 | 453 |

All values are medians. This is a separate dataset, not the base column of the isolated comparison. The deployment changed from f558 to 8b4 during that run; 8b4 only changed the private app header, not the measured public pages. The first cold landing sample had TTFB1115ms and LCP2518ms, showing variation hidden by medians.
