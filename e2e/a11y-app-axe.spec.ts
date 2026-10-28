import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Accesibilidad de las pantallas de la app (sesion E2E) con axe-core,
// en escritorio y movil. Cubre lo que el barrido publico no ve:
// - jerarquia de encabezados (h1 -> h2 -> h3 sin saltos) en /inicio,
//   /screener y /export (regresion: CardTitle h3 directo bajo el h1);
// - label-in-name (WCAG 2.5.3): el nombre accesible contiene el texto
//   visible. Regresion: el gatillo del buscador ("Buscar acciones...")
//   llevaba aria-label="Abrir buscador" y el menu de usuario
//   aria-label="Menu de usuario" con el nombre visible debajo.
// axe-core llega de forma transitiva (eslint-config-next ->
// eslint-plugin-jsx-a11y); se inyecta el bundle instalado, sin dependencia
// nueva. label-content-name-mismatch viene desactivada por defecto en axe
// (experimental): se activa explicitamente, igual que hace Lighthouse.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const require = createRequire(resolve(process.cwd(), "package.json"));
const AXE_SOURCE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const APP_ROUTES = ["/inicio", "/screener", "/export"];
const VIEWPORTS = [
  { name: "escritorio", width: 1366, height: 768 },
  { name: "movil", width: 390, height: 844 },
];

type AxeViolation = { id: string; impact: string | null; help: string; nodes: { target: string[] }[] };

async function audit(page: Page): Promise<AxeViolation[]> {
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
  await page.addScriptTag({ content: AXE_SOURCE });
  return page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (ctx: Document, opts: object) => Promise<{ violations: AxeViolation[] }> } }).axe;
    const result = await axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
      rules: { "label-content-name-mismatch": { enabled: true }, "heading-order": { enabled: true } },
    });
    return result.violations;
  });
}

async function expectAuthenticatedRoute(page: Page, path: string) {
  await expect.poll(() => new URL(page.url()).pathname).toBe(path);
  await expect(page.locator("main#content")).toBeVisible();
  await expect(page.locator('header a[href="/alerts"]')).toBeVisible();
  await expect(page.locator("main#content").getByRole("heading", { level: 1 })).toBeVisible();
}

for (const vp of VIEWPORTS) {
  for (const path of APP_ROUTES) {
    test(`a11y app ${path} (${vp.name}): sin violaciones axe`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      const response = await page.goto(path);
      expect(response?.status(), `${path} respondio ${response?.status()}`).toBeLessThan(400);
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await expectAuthenticatedRoute(page, path);
      const violations = await audit(page);
      const report = violations
        .map((v) => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.slice(0, 5).map((n) => n.target.join(" ")).join("\n  ")}`)
        .join("\n");
      expect(violations, report).toEqual([]);
    });
  }

  test(`a11y header (${vp.name}): nombre accesible = texto visible en gatillos`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto("/inicio");
    await page.waitForLoadState("networkidle").catch(() => undefined);
    await expectAuthenticatedRoute(page, "/inicio");
    const violations = (await audit(page)).filter((v) => v.id === "label-content-name-mismatch");
    const report = violations
      .map((v) => v.nodes.slice(0, 5).map((n) => n.target.join(" ")).join("\n"))
      .join("\n");
    expect(violations, report).toEqual([]);
  });
}
