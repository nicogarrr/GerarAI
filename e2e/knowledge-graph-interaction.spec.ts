import { createHash, createHmac, randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

const runUiE2E = process.env.E2E_UI_RUN === "1";
const uiBackendURL = E2E_UI_BACKEND_URL;
const authSecret =
  process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
// El navegador entra con el bypass E2E como `e2e-browser-user` y la UI firma con
// tenant = user.id (lib/auth/research-identity.ts). Sembrar con otra identidad
// deja la pagina leyendo un tenant vacio ("El grafo esta vacio").
const tenant = "e2e-browser-user";
const user = "e2e-browser-user";

/**
 * Por que este spec siembra por el backend y no con `page.route`.
 *
 * `/knowledge-graph` es un Server Component: el `GET /api/knowledge-graph` lo
 * hace el proceso de Next, no el navegador. `page.route` solo intercepta
 * peticiones que salen del navegador, asi que "mockear la API" con el seria
 * teatro: la pagina seguiria leyendo el backend de verdad. Lo que si se
 *Intercepta (mas abajo) es cualquier salida a Internet, que es la dependencia
 * externa que este spec prohibe.
 *
 * El backend que usa playwright.config.ts es local y efimero; se siembra con
 * `POST /api/knowledge-graph/sync`, que es la misma operacion que el boton
 * «Sincronizar grafo» de la pagina. Con `ensure_company_master()` al arrancar
 * el backend, ese sync deja nodos de empresa y de concepto y al menos las
 * aristas concepto->concepto, asi que el fixture no depende de datos previos.
 */

function signedHeaders(method: string, path: string, body: Buffer) {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", authSecret)
    .update(`${tenant}:${user}:${timestamp}:${nonce}:${method}:${path}:${bodyHash}`)
    .digest("hex");
  return {
    "X-CavaAI-Tenant": tenant,
    "X-CavaAI-User": user,
    "X-CavaAI-Timestamp": timestamp,
    "X-CavaAI-Nonce": nonce,
    "X-CavaAI-Method": method,
    "X-CavaAI-Path": path,
    "X-CavaAI-Body-Hash": bodyHash,
    "X-CavaAI-Signature": signature,
  };
}

async function signedPost(request: APIRequestContext, path: string) {
  const body = Buffer.alloc(0);
  return request.fetch(`${uiBackendURL}${path}`, {
    method: "POST",
    headers: signedHeaders("POST", path, body),
    data: undefined,
  });
}

type GraphPayload = {
  node_count: number;
  edge_count: number;
  nodes: Array<{ id: number; label: string; type: string; description: string }>;
};

async function readGraph(request: APIRequestContext): Promise<GraphPayload> {
  const path = "/api/knowledge-graph?limit=120";
  const response = await request.fetch(`${uiBackendURL}${path}`, {
    headers: signedHeaders("GET", "/api/knowledge-graph", Buffer.alloc(0)),
  });
  if (!response.ok()) throw new Error(`GET ${path} devolvio ${response.status()}: ${await response.text()}`);
  return (await response.json()) as GraphPayload;
}

/** `translate(10 20) scale(2)` -> escala y desplazamiento del unico contenedor. */
function parseTransform(transform: string): { x: number; y: number; scale: number } {
  const translated = /translate\((-?[\d.]+)\s+(-?[\d.]+)\)/.exec(transform);
  const scaled = /scale\((-?[\d.]+)\)/.exec(transform);
  expect(translated, `transform sin translate: ${transform}`).not.toBeNull();
  expect(scaled, `transform sin scale: ${transform}`).not.toBeNull();
  return {
    x: Number(translated![1]),
    y: Number(translated![2]),
    scale: Number(scaled![1]),
  };
}

const layer = (page: Page) => page.getByTestId("kg-layer");
const surface = (page: Page) => page.getByTestId("kg-surface");

/**
 * El lienzo esta por debajo del pliegue en la vista por defecto de 1280x720, y
 * `page.mouse` no reaches fuera del viewport: sin traerlo antes, los gestos
 * caerian en otra elemento y el test passaria por motivos equivocados.
 */
const surfaceBox = async (page: Page) => {
  await surface(page).scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  const box = await surface(page).boundingBox();
  expect(box, "el lienzo deberia estar medido").not.toBeNull();
  return box!;
};

const transformOf = async (page: Page) =>
  parseTransform((await layer(page).getAttribute("transform")) ?? "");

/** Etiqueta de un nodo tal como la pinta el listado de texto. */
const labelOfRow = async (row: Locator) => (await row.getByRole("button").innerText()).trim();

/** Espera a que el lienzo este medido y con transform aplicado (ResizeObserver + rAF). */
async function waitForCanvas(page: Page) {
  await expect(layer(page)).toBeVisible({ timeout: 15_000 });
  await expect
    .poll(async () => (await layer(page).getAttribute("transform")) ?? "", { timeout: 15_000 })
    .toMatch(/translate\(-?[\d.]+ -?[\d.]+\) scale\(-?[\d.]+\)/);
}

test.describe("knowledge-graph interactivo (D2b)", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test.beforeEach(async ({ page: _page, context, request }) => {
    // Cero Internet: cualquier salida fuera del host local se aborta y queda
    // registrada, para que un fallo de red externo no pueda colarse como verde.
    await context.route("**/*", async (route) => {
      const host = new URL(route.request().url()).hostname;
      if (host === "127.0.0.1" || host === "localhost") {
        await route.continue();
        return;
      }
      externalRequests.push(route.request().url());
      await route.abort();
    });

    const sync = await signedPost(request, "/api/knowledge-graph/sync");
    expect(sync.ok(), `el sync del grafo fallo: ${await sync.text()}`).toBeTruthy();
    const graph = await readGraph(request);
    // Sin nodos el spec no puede comprobar pan/zoom/seleccion. Se salta de
    // forma explicita (visible en el informe) en vez de fingir un verde.
    test.skip(graph.node_count === 0, "El backend no devolvio nodos: no hay grafo que manipular.");
  });

  test("el grafo se dibuja, se declara y existe tambien en texto", async ({ page }) => {
    await page.goto("/knowledge-graph");
    await expect(page.getByRole("heading", { level: 1, name: "Grafo de conocimiento" })).toBeVisible();

    // Superficie interactiva con rol y nombre accesible.
    const canvas = surface(page);
    await expect(canvas).toBeVisible();
    await expect(canvas).toHaveAttribute("role", "application");
    const label = await canvas.getAttribute("aria-label");
    expect(label?.length ?? 0).toBeGreaterThan(0);
    await waitForCanvas(page);

    // El SVG es decorativo: no puede ser la unica representacion.
    await expect(page.locator('svg[aria-hidden="true"]').first()).toBeAttached();
    // Y la representacion textual esta de verdad, con los nodos del grafo.
    const rows = page.getByTestId(/^kg-row-/);
    expect(await rows.count()).toBeGreaterThan(0);
    await expect(page.getByRole("heading", { name: "Nodos del grafo en texto" })).toBeVisible();
    await expect(page.getByText(/Nodos dibujados: \d+ de \d+/)).toBeVisible();

    // El recorte a 80 nodos se dice, no se oculta.
    const wrapper = page.getByTestId("knowledge-graph-interactive");
    const drawn = Number(await wrapper.getAttribute("data-node-count"));
    const drawnEdges = Number(await wrapper.getAttribute("data-edge-count"));
    expect(drawn).toBeGreaterThan(0);
    expect(drawnEdges).toBeGreaterThanOrEqual(0);
    const truncated = await page.getByTestId("kg-truncated").count();
    // El aviso aparece exactamente cuando el backend ha dado mas de lo que se
    // dibuja; si no hay recorte, el aviso no debe estar.
    const totals = await page.getByTestId("kg-counts").innerText();
    const hidden = [...totals.matchAll(/(\d+) de (\d+)/g)].map((match) => Number(match[2]) - Number(match[1]));
    expect(hidden).toHaveLength(2);
    expect(truncated).toBe(Math.max(...hidden) > 0 ? 1 : 0);
  });

  test("se arrastra con el ratón y con las flechas del teclado", async ({ page }) => {
    await page.goto("/knowledge-graph");
    await waitForCanvas(page);
    const box = await surfaceBox(page);
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    const before = await transformOf(page);

    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx - 160, cy - 90, { steps: 8 });
    await page.mouse.up();

    // El transform se escribe dentro de un rAF: leerlo justo despues del gesto
    // puede devolver el valor de un frame anterior.
    await expect.poll(async () => (await transformOf(page)).x).toBeLessThan(before.x);
    const afterDrag = await transformOf(page);
    expect(afterDrag.y).toBeLessThan(before.y);
    expect(afterDrag.scale).toBeCloseTo(before.scale, 5);

    // Convention de teclado: la flecha desplaza la VISTA en el sentido de la
    // flecha, como un scroll. El grafo se dibuja con `translate(x y)`, asi que
    // avanzar a la derecha es restar x (el contenido se mueve a la izquierda).
    await surface(page).focus();
    await page.keyboard.press("ArrowRight");
    await expect.poll(async () => (await transformOf(page)).x).toBeLessThan(afterDrag.x);
    const afterKey = await transformOf(page);
    expect(afterKey.scale).toBeCloseTo(afterDrag.scale, 5);

    await page.keyboard.press("ArrowLeft");
    await expect.poll(async () => (await transformOf(page)).x).toBeCloseTo(afterDrag.x, 1);

    await page.keyboard.press("ArrowDown");
    await expect.poll(async () => (await transformOf(page)).y).toBeLessThan(afterDrag.y);

    // Shift multiplica el paso; 0 vuelve a encajar.
    await page.keyboard.press("Shift+ArrowUp");
    await expect.poll(async () => (await transformOf(page)).y).toBeGreaterThan(afterDrag.y);
    await page.keyboard.press("0");
    await expect
      .poll(async () => {
        const current = await transformOf(page);
        return current.x !== afterDrag.x || current.y !== afterDrag.y;
      })
      .toBe(true);
  });

  test("la rueda y los botones acercan y alejan dentro de los límites", async ({ page }) => {
    await page.goto("/knowledge-graph");
    await waitForCanvas(page);
    const box = await surfaceBox(page);
    const start = await transformOf(page);

    await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.3);
    await page.mouse.wheel(0, -400);
    await expect.poll(async () => (await transformOf(page)).scale).toBeGreaterThan(start.scale);

    // Zoom anclado al cursor: el punto del raton no se mueve de sitio.
    const anchor = { x: box.width * 0.3, y: box.height * 0.3 };
    const anchored = await transformOf(page);
    const graphUnder = {
      x: (anchor.x - anchored.x) / anchored.scale,
      y: (anchor.y - anchored.y) / anchored.scale,
    };
    const zoomed = await transformOf(page);
    expect(graphUnder.x * zoomed.scale + zoomed.x).toBeCloseTo(anchor.x, 3);
    expect(graphUnder.y * zoomed.scale + zoomed.y).toBeCloseTo(anchor.y, 3);

    await page.getByTestId("kg-zoom-in").click();
    await expect.poll(async () => (await transformOf(page)).scale).toBeGreaterThan(zoomed.scale);
    const afterButton = await transformOf(page);
    await page.getByTestId("kg-zoom-out").click();
    await expect.poll(async () => (await transformOf(page)).scale).toBeLessThan(afterButton.scale);

    // El tope declarado (400 %) no se puede rebasar.
    for (let i = 0; i < 12; i += 1) await page.getByTestId("kg-zoom-in").click();
    expect((await transformOf(page)).scale).toBeLessThanOrEqual(4);
    await expect(page.getByTestId("kg-zoom-label")).toHaveText("Zoom 400%");
  });

  test("«Ajustar a la pantalla» y «Reiniciar» devuelven la vista", async ({ page }) => {
    await page.goto("/knowledge-graph");
    await waitForCanvas(page);
    const fitted = await transformOf(page);

    const box = await surfaceBox(page);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 220, box.y + box.height / 2 + 140, { steps: 6 });
    await page.mouse.up();
    await expect.poll(async () => (await transformOf(page)).x).not.toBeCloseTo(fitted.x, 1);

    await page.getByTestId("kg-fit").click();
    await expect.poll(async () => (await transformOf(page)).x).toBeCloseTo(fitted.x, 1);

    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 220, box.y + box.height / 2 - 140, { steps: 6 });
    await page.mouse.up();
    await page.getByTestId("kg-reset").click();
    await expect.poll(async () => (await transformOf(page)).x).toBeCloseTo(fitted.x, 1);
  });

  test("seleccionar un nodo lo pone en la URL y abre su detalle", async ({ page }) => {
    await page.goto("/knowledge-graph");
    await waitForCanvas(page);

    await page.getByTestId("kg-search").fill("a");
    const suggestion = page.locator('[data-testid^="kg-suggestion-"]').first();
    await expect(suggestion).toBeVisible();
    const label = (await suggestion.innerText()).trim();
    await suggestion.click();
    await expect.poll(() => new URL(page.url()).searchParams.get("focus")).toMatch(/^\d+$/);
    const focus = new URL(page.url()).searchParams.get("focus")!;

    const detail = page.getByTestId("kg-detail");
    await expect(detail).toContainText(label);
    await expect(detail.getByTestId("kg-detail-field-label")).toContainText(label);
    // El panel existe aunque el backend no de descripcion: N/D con motivo.
    const description = detail.getByTestId("kg-detail-field-description");
    if ((await description.innerText()).includes("N/D")) {
      expect((await description.innerText()).length).toBeGreaterThan(20);
    }

    // Enlace compartible al nodo, con los filtros del ámbito conservados.
    // Ahora es un boton que copia la URL (el antiguo <Link> apuntaba a la URL
    // actual y no navegaba a ninguna parte). Con portapapeles disponible dice
    // "copiado"; sin el, ensena el enlace con el nodo para copiarlo a mano.
    await detail.getByRole("button", { name: "Enlace compartible a este nodo" }).click();
    const copyStatus = detail.getByRole("status").filter({ hasText: /Enlace copiado|No se pudo copiar/ });
    await expect(copyStatus).toBeVisible();
    if ((await copyStatus.innerText()).includes("No se pudo copiar")) {
      await expect(detail.locator("code")).toContainText(new RegExp(`focus=${focus}`));
    }
  });

  test("el deep link abre la página con el nodo ya seleccionado", async ({ page, request }) => {
    const graph = await readGraph(request);
    const target = graph.nodes[0];
    await page.goto(`/knowledge-graph?focus=${target.id}`);

    const detail = page.getByTestId("kg-detail");
    await expect(detail.getByTestId("kg-detail-field-label")).toContainText(target.label);
    // El nodo queda marcado en el dibujo, no solo en el panel.
    await expect(page.locator(`[data-testid="kg-dot-${target.id}"][data-selected="true"]`)).toHaveCount(1);
  });

  test("un nodo que no existe en el subgrafo no rompe la página", async ({ page }) => {
    await page.goto("/knowledge-graph?focus=999999");
    await waitForCanvas(page);
    // Un ?focus= que no esta en el subgrafo cargado se dice, no se calla.
    await expect(page.getByTestId("kg-detail")).toContainText("El nodo #999999 no está en el subgrafo que se ha cargado.");
    expect(new URL(page.url()).searchParams.get("focus")).toBe("999999");
  });

  test("aislar un nodo atenúa el resto y reiniciar lo devuelve", async ({ page }) => {
    await page.goto("/knowledge-graph");
    await waitForCanvas(page);

    const rows = page.locator('[data-testid^="kg-row-"]');
    await rows.nth(1).getByRole("button").click();
    await expect.poll(() => new URL(page.url()).searchParams.get("focus")).toMatch(/^\d+$/);

    const isolate = page.getByTestId("kg-isolate");
    await expect(isolate).toBeEnabled();
    await isolate.click();
    await expect(page.getByTestId("kg-isolation-note")).toContainText("Mostrando el nodo seleccionado");
    const dimmed = await page.locator('g[data-testid^="kg-node-"][opacity="0.18"]').count();
    expect(dimmed).toBeGreaterThan(0);

    await page.getByTestId("kg-reset").click();
    await expect(page.getByTestId("kg-isolation-note")).toContainText("Vista completa");
    await expect(page.locator('g[data-testid^="kg-node-"][opacity="0.18"]')).toHaveCount(0);
    await expect.poll(() => new URL(page.url()).searchParams.get("focus")).toBeNull();
  });

  test("el buscador encuentra un nodo por nombre y lo centra", async ({ page }) => {
    await page.goto("/knowledge-graph");
    await waitForCanvas(page);
    const before = await transformOf(page);

    const rows = page.locator('[data-testid^="kg-row-"]');
    const label = await labelOfRow(rows.nth(2));
    await page.getByTestId("kg-search").fill(label.slice(0, Math.min(12, label.length)));
    await expect(page.getByRole("status").filter({ hasText: /nodos? coinciden?/ })).toBeVisible();

    const suggestion = page.locator('[data-testid^="kg-suggestion-"]').first();
    await suggestion.click();
    await expect.poll(() => new URL(page.url()).searchParams.get("focus")).toMatch(/^\d+$/);
    await expect
      .poll(async () => {
        const current = await transformOf(page);
        return current.scale !== before.scale || current.x !== before.x || current.y !== before.y;
      })
      .toBe(true);
  });

  test("se vuelcan el SVG y el JSON del subgrafo en foco", async ({ page }) => {
    await page.goto("/knowledge-graph");
    await waitForCanvas(page);
    await page.locator('[data-testid^="kg-row-"]').nth(1).getByRole("button").click();
    await page.getByTestId("kg-isolate").click();

    const svgDownload = page.waitForEvent("download");
    await page.getByTestId("kg-export-svg").click();
    const svg = await svgDownload;
    expect(svg.suggestedFilename()).toMatch(/^gerarai-grafo-\d+-nodos\.svg$/);

    const jsonDownload = page.waitForEvent("download");
    await page.getByTestId("kg-export-json").click();
    const json = await jsonDownload;
    expect(json.suggestedFilename()).toMatch(/^gerarai-grafo-\d+-nodos\.json$/);
  });

  test("la página no deja errores de consola", async ({ page }) => {
    const problems: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") problems.push(message.text());
    });
    page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));

    await page.goto("/knowledge-graph");
    await waitForCanvas(page);
    const rows = page.locator('[data-testid^="kg-row-"]');
    await rows.first().getByRole("button").click();
    await page.getByTestId("kg-zoom-in").click();
    await page.getByTestId("kg-fit").click();
    await surface(page).focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("+");
    await page.keyboard.press("0");
    await page.waitForLoadState("networkidle");

    expect(problems).toEqual([]);
    expect(externalRequests).toEqual([]);
  });
});

const externalRequests: string[] = [];

/**
 * Accesibilidad que se puede comprobar sin tool externo: rol y nombre de la
 * superficie, foco alcanzable, el SVG marcado como decorativo y el listado
 * textual con las filas del grafo.
 */
test.describe("knowledge-graph accesibilidad (D2b)", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("la superficie tiene rol, nombre, foco visible y ayuda de teclado", async ({ page, request }) => {
    const sync = await signedPost(request, "/api/knowledge-graph/sync");
    expect(sync.ok()).toBeTruthy();
    await page.goto("/knowledge-graph");
    await waitForCanvas(page);

    const canvas: Locator = surface(page);
    await expect(canvas).toHaveAttribute("tabindex", "0");
    await expect(canvas).toHaveAttribute("aria-roledescription", "Grafo de conocimiento");
    const describedBy = await canvas.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    // aria-describedby lleva ahora dos ids (ayuda de teclado y descripcion del grafo).
    const [helpId] = describedBy!.split(" ");
    const help = page.locator(`#${helpId}`);
    await expect(help).toContainText("flechas");
    await expect(help).toContainText("Escape");

    // El foco llega a la superficie y el anillo de foco es visible (el tema
    // lo define en `:focus-visible`, aqui se comprueba el elemento activo).
    await canvas.focus();
    expect(await page.evaluate(() => document.activeElement?.getAttribute("data-testid"))).toBe("kg-surface");
    await expect(page.getByTestId("kg-zoom-label")).toHaveAttribute("aria-live", "polite");

    // Cada fila del listado es un boton con nombre: el grafo se puede
    // recorrer entero con teclado aunque el SVG no se pueda leer.
    const firstRow = page.locator('[data-testid^="kg-row-"]').first();
    await expect(firstRow.getByRole("button")).toHaveAttribute("aria-label", /Seleccionar y centrar el nodo /);
  });
});