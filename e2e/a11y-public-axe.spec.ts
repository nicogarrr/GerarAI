import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Accesibilidad de las paginas publicas con axe-core (WCAG 2.1 A/AA).
// Sin claves de pago ni backend con datos: son las rutas que ve cualquiera
// antes de entrar. Se falla solo por impacto serio o critico, que es lo que
// bloquea de verdad a quien usa lector de pantalla o tiene baja vision; los
// avisos menores no tumban CI.
//
// axe-core llega hoy de forma transitiva (eslint-config-next ->
// eslint-plugin-jsx-a11y); se inyecta el bundle del propio paquete instalado,
// sin dependencia nueva.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const require = createRequire(resolve(process.cwd(), "package.json"));
const AXE_SOURCE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const PUBLIC_ROUTES = ["/", "/sign-in", "/sign-up", "/metodologia", "/help"];

type AxeNode = { target: string[]; html: string };
type AxeViolation = { id: string; impact: string | null; help: string; nodes: AxeNode[] };

async function seriousViolations(page: Page): Promise<AxeViolation[]> {
  // El overlay de dev de Next no es parte de la app.
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
  await page.addScriptTag({ content: AXE_SOURCE });
  const violations = await page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (ctx: Document, opts: object) => Promise<{ violations: AxeViolation[] }> } }).axe;
    const result = await axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    });
    return result.violations;
  });
  return violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

for (const path of PUBLIC_ROUTES) {
  test(`a11y ${path}: sin violaciones axe serias`, async ({ page }) => {
    const response = await page.goto(path);
    expect(response?.status(), `${path} respondio ${response?.status()}`).toBeLessThan(400);
    await page.waitForLoadState("networkidle").catch(() => undefined);
    const violations = await seriousViolations(page);
    const report = violations
      .map((v) => `${v.id} (${v.impact}): ${v.help}\n  ${v.nodes.slice(0, 5).map((n) => n.target.join(" ")).join("\n  ")}`)
      .join("\n");
    expect(violations, report).toEqual([]);
  });
}

test("a11y /help: la jerarquia de titulos no salta niveles", async ({ page }) => {
  await page.goto("/help");
  const levels = await page.locator("main h1, main h2, main h3, main h4").evaluateAll((els) =>
    els.filter((el) => (el as HTMLElement).offsetParent !== null).map((el) => Number(el.tagName.slice(1))),
  );
  expect(levels[0], "la pagina debe abrir con un h1").toBe(1);
  for (let i = 1; i < levels.length; i += 1) {
    expect(levels[i] - levels[i - 1], `salto de h${levels[i - 1]} a h${levels[i]}`).toBeLessThanOrEqual(1);
  }
});
