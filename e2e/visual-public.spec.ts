import { test } from "@playwright/test";

// Capturas deterministas de las paginas publicas para visual regression.
// NO se versionan PNGs en git (el repo ya arrastra historial de snapshots):
// las baselines viven como artefacto del workflow en main y el job de PR
// las descarga y compara con reg-cli. Rutas publicas: no necesitan backend
// con datos ni auth, asi que el fixture es estable entre runs.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const ROUTES = ["/", "/sign-in", "/sign-up", "/metodologia", "/help"];
const VIEWPORTS = [
  { name: "mobile", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
];

for (const vp of VIEWPORTS) {
  test(`visual public ${vp.name}`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    for (const route of ROUTES) {
      await page.goto(route, { waitUntil: "networkidle" });
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      const name = `${route === "/" ? "home" : route.slice(1)}-${vp.name}.png`;
      await page.screenshot({ path: `test-results/visual/${name}`, fullPage: true });
    }
  });
}
