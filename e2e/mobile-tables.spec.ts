import { createHash, createHmac, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const runUiE2E = process.env.E2E_UI_RUN === "1";

const uiBackendURL = process.env.E2E_UI_BACKEND_URL ?? "http://127.0.0.1:8100";
const e2eResearchSecret =
  process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";

// Las rutas /research/AAPL/* solo renderizan cabecera si la empresa existe:
// el spec asegura su propio dato en vez de depender de otros specs. Firma ligada al request
// (nonce + metodo + ruta + sha256 del cuerpo), la misma que
// e2e/fixtures/research-api.ts: sirve contra backend leniente y contra
// research_auth_strict_binding=True (el default).
test.beforeAll(async () => {
  if (!runUiE2E) return;
  const path = "/api/companies/ensure";
  const body = JSON.stringify({ ticker: "AAPL", name: "Apple Inc." });
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", e2eResearchSecret)
    .update(`e2e-api-tenant:e2e-api-user:${timestamp}:${nonce}:POST:${path}:${bodyHash}`)
    .digest("hex");
  const res = await fetch(`${uiBackendURL}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-CavaAI-Tenant": "e2e-api-tenant",
      "X-CavaAI-User": "e2e-api-user",
      "X-CavaAI-Timestamp": timestamp,
      "X-CavaAI-Nonce": nonce,
      "X-CavaAI-Method": "POST",
      "X-CavaAI-Path": path,
      "X-CavaAI-Body-Hash": bodyHash,
      "X-CavaAI-Signature": signature,
    },
    body,
  });
  if (!res.ok) throw new Error(`ensure AAPL fallo: ${res.status} ${await res.text()}`);
});

function source(...parts: string[]): string {
  return readFileSync(resolve(process.cwd(), ...parts), "utf8");
}

// iPhone 14 viewport: 390x844 con táctil.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

// Las páginas con datos tabulares deben renderizar cards o tablas con scroll
// interno: la página nunca desborda horizontalmente. Si una tabla es más
// ancha que el viewport, debe vivir dentro de un contenedor con
// overflow-x auto/scroll.
async function expectTablesScrollInside(page: Page, route: string) {
  const report = await page.evaluate(() => {
    const pageOverflow =
      document.documentElement.scrollWidth <= window.innerWidth + 1;
    const tables = Array.from(document.querySelectorAll("table"));
    const bad: string[] = [];
    for (const table of tables) {
      const rect = table.getBoundingClientRect();
      if (rect.width <= window.innerWidth + 1) continue;
      let el: HTMLElement | null = table.parentElement;
      let contained = false;
      while (el) {
        const style = getComputedStyle(el);
        if (
          (style.overflowX === "auto" || style.overflowX === "scroll") &&
          el.getBoundingClientRect().width <= window.innerWidth + 1
        ) {
          contained = true;
          break;
        }
        el = el.parentElement;
      }
      if (!contained) {
        bad.push(
          `tabla de ${Math.round(rect.width)}px sin contenedor de scroll interno`,
        );
      }
    }
    return {
      pageOverflow,
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      tableCount: tables.length,
      bad,
    };
  });
  expect(
    report.pageOverflow,
    `${route}: overflow de página scrollWidth=${report.scrollWidth} > innerWidth=${report.innerWidth}`,
  ).toBe(true);
  expect(
    report.bad,
    `${route}: ${report.bad.join("; ")} (${report.tableCount} tablas)`,
  ).toEqual([]);
}

const TABLE_ROUTES = [
  { path: "/watchlist", heading: "Watchlist" },
  { path: "/portfolio", heading: undefined },
  { path: "/research/MSFT", heading: "MSFT" },
  { path: "/risk", heading: undefined },
  { path: "/plan", heading: undefined },
  { path: "/taxes", heading: undefined },
  { path: "/corporate-actions", heading: undefined },
  { path: "/ownership", heading: undefined },
  { path: "/screeners", heading: undefined },
  { path: "/screener?vista=subidas", heading: "Explorar acciones" },
  { path: "/screener", heading: "Explorar acciones" },
  { path: "/research/news", heading: "Eventos de noticias" },
  { path: "/research/sources", heading: "Fuentes" },
  // Desde la fila de seis pestañas (29-oct-2026) estas URLs redirigen a su
  // sección dentro de la ficha (Finanzas#terminal, Valoración#supuestos).
  { path: "/research/AAPL/financial-terminal", heading: "AAPL" },
  { path: "/research/AAPL/driver-assumptions", heading: "AAPL" },
  { path: "/portfolio/intelligence", heading: "Inteligencia de cartera" },
];

test.describe("mobile tablas con scroll interno", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  for (const route of TABLE_ROUTES) {
    test(`${route.path} renderiza cards o tabla contenida, sin overflow`, async ({
      page,
    }) => {
      await page.goto(route.path);
      await expect(page.locator("main, body").first()).toBeVisible();
      await expect(page.getByText(/Application error|Something went wrong/i)).toHaveCount(0);
      if (route.heading) {
        await expect(
          page.getByRole("heading", { name: route.heading, level: 1 }),
        ).toBeVisible();
      }
      await expectTablesScrollInside(page, route.path);
    });
  }
});

/**
 * Comprobaciones estáticas: corren sin backend ni navegador, así que son la
 * única red de seguridad cuando la app no levanta (CI sin data-engine).
 */
test.describe("tablas: semántica y fallback móvil (estático)", () => {
  test("TableHead emite scope por defecto y acepta override", () => {
    const table = source("components", "ui", "table.tsx");

    // Sin `scope` un lector de pantalla no anuncia la cabecera de columna.
    expect(table).toContain('scope = "col"');
    expect(table).toContain("scope={scope}");
    // El caption se queda en el DOM (es lo que nombra la tabla).
    expect(table).toContain("TableCaption");
    // Densidades: la de shadcn por defecto (`h-12 px-4`) y la compacta, que se
    // expresa con las utilidades de grupo px-3/py-2 sobre la variante de datos.
    expect(table).toContain("h-12 px-4");
    expect(table).toContain("group-data-[dense]/table:px-3");
    expect(table).toContain("group-data-[dense]/table:py-2");
    // La densidad es de tabla entera: sin override por fila/celda (las clases
    // directas y las de grupo colisionarian por orden de la hoja).
    expect(table).not.toContain("dense === false");
    // La densidad se propaga por CSS (`data-dense` + variante group-data), no
    // por un contexto de React: este modulo lo importan server components y en
    // el runtime de RSC `createContext` no existe (rompia `next build`).
    expect(table).toContain('data-dense={dense ? "" : undefined}');
    expect(table).toContain("group-data-[dense]/table");
    expect(table).not.toContain("React.createContext(");
  });

  test("RecordViews limita columnas y ofrece cards en móvil", () => {
    const recordViews = source("components", "data", "RecordViews.tsx");

    // Sin tope, 6 columnas + "Acciones" no caben y el contenedor scrollea.
    expect(recordViews).toContain("function pickColumns(records: DataRecord[], preferred?: string[], max:");
    expect(recordViews).not.toContain("matchMedia");
    // Tabla solo desde md; cards equivalentes por debajo.
    expect(recordViews).toContain("hidden overflow-x-auto md:block");
    expect(recordViews).toContain("md:hidden");
    expect(recordViews).toContain("TableCaption");
  });

  test("RiskDashboardView ofrece cards en móvil además de la tabla", () => {
    const risk = source("components", "risk", "RiskDashboardView.tsx");

    expect(risk).toContain("hidden overflow-x-auto md:block");
    expect(risk).toContain("md:hidden");
    expect(risk).toContain("TableCaption");
  });

  test("las tablas nativas llevan caption y scope en cada columna", () => {
    const nativeTables = [
      ["app", "(root)", "ownership", "page.tsx"],
      ["app", "(root)", "screeners", "page.tsx"],
      ["app", "(root)", "knowledge", "page.tsx"],
      ["app", "(root)", "knowledge-graph", "page.tsx"],
      ["components", "research", "NewsEventsFlow.tsx"],
      ["app", "(root)", "research", "sources", "page.tsx"],
      ["app", "(root)", "research", "[ticker]", "page.tsx"],
      // Tras la extracción de secciones (#3038) las tablas viven en los Section,
      // no en las páginas: la página solo compone.
      ["components", "research", "sections", "FinancialTerminalSection.tsx"],
      ["components", "research", "sections", "DriverAssumptionsSection.tsx"],
      ["app", "(root)", "portfolio", "intelligence", "page.tsx"],
      ["app", "(root)", "screener", "page.tsx"],
      ["components", "market", "MoversTable.tsx"],
      ["components", "proPicks", "WalkForwardResults.tsx"],
      ["components", "research", "FundamentalModelPanels.tsx"],
    ] as const;

    const problems: string[] = [];
    for (const parts of nativeTables) {
      const file = parts.join("/");
      const text = source(...parts);
      const tables = text.match(/<table[\s>]/g)?.length ?? 0;
      if (tables === 0) {
        problems.push(`${file}: sin <table>`);
        continue;
      }
      if (!text.includes("<caption")) problems.push(`${file}: sin <caption>`);
      // Cada <th> de cabecera necesita scope; los <th> de fila, scope="row".
      const heads = text.match(/<th\b[^>]*>/g) ?? [];
      for (const head of heads) {
        if (!/\bscope=/.test(head)) problems.push(`${file}: <th> sin scope -> ${head.slice(0, 60)}`);
      }
      if (!/\bscope="row"/.test(text) && file !== "app/(root)/screener/page.tsx") {
        // /screener mantiene <td> en la primera celda: e2e/investor-screener la localiza por etiqueta.
        problems.push(`${file}: sin scope="row"`);
      }
    }
    expect(problems).toEqual([]);
  });

  test("cada contenedor con scroll horizontal de tabla es alcanzable por teclado", () => {
    // Solo <div> nativos: en las tablas de shadcn el contenedor que scrollea es
    // el wrapper interno de <Table>, que recibe la región (ver test siguiente).
    const regions = [
      ["app", "(root)", "ownership", "page.tsx"],
      ["app", "(root)", "screeners", "page.tsx"],
      ["app", "(root)", "knowledge", "page.tsx"],
      ["app", "(root)", "knowledge-graph", "page.tsx"],
      ["components", "research", "NewsEventsFlow.tsx"],
      ["app", "(root)", "research", "sources", "page.tsx"],
      ["app", "(root)", "research", "[ticker]", "page.tsx"],
      // Tras la extracción de secciones (#3038) las tablas viven en los Section,
      // no en las páginas: la página solo compone.
      ["components", "research", "sections", "FinancialTerminalSection.tsx"],
      ["components", "research", "sections", "DriverAssumptionsSection.tsx"],
      ["app", "(root)", "portfolio", "intelligence", "page.tsx"],
      ["app", "(root)", "screener", "page.tsx"],
      ["components", "market", "MoversTable.tsx"],
      ["components", "proPicks", "WalkForwardResults.tsx"],
      ["components", "research", "FundamentalModelPanels.tsx"],
    ] as const;

    const problems: string[] = [];
    for (const parts of regions) {
      const file = parts.join("/");
      const text = source(...parts);
      // Todo contenedor con overflow-x-auto debe ser una región enfocable:
      // con teclado no hay barra de scroll (WCAG 2.1.1).
      const scrollers = text.match(/<div[^>]*overflow-x-auto[^>]*>/g) ?? [];
      for (const scroller of scrollers) {
        if (!/tabIndex=\{0\}/.test(scroller)) problems.push(`${file}: sin tabIndex -> ${scroller.slice(0, 80)}`);
        if (!/role="region"/.test(scroller)) problems.push(`${file}: sin role="region" -> ${scroller.slice(0, 80)}`);
        if (!/aria-label=/.test(scroller)) problems.push(`${file}: sin aria-label -> ${scroller.slice(0, 80)}`);
      }
    }
    expect(problems).toEqual([]);
  });

  test("las tablas shadcn nombran su región con scroll y se montan en la línea base", () => {
    const shadcnTables = [
      ["app", "(root)", "watchlist", "page.tsx"],
      ["components", "data", "RecordViews.tsx"],
      ["components", "risk", "RiskDashboardView.tsx"],
    ] as const;

    const problems: string[] = [];
    for (const parts of shadcnTables) {
      const file = parts.join("/");
      const text = source(...parts);
      if (!/<Table[^>]*regionLabel=/.test(text)) problems.push(`${file}: <Table> sin regionLabel`);
      if (!text.includes("TableCaption")) problems.push(`${file}: sin TableCaption`);
    }
    // El wrapper de <Table> es el que scrollea: region + tabIndex + aria-label.
    const table = source("components", "ui", "table.tsx");
    expect(table).toContain('role: "region"');
    expect(table).toContain('"aria-label": regionLabel');
    expect(table).toContain("tabIndex: 0");
    expect(problems).toEqual([]);
  });
});
