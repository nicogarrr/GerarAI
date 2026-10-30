import { expect, test } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { seedMarketPrices } from "./fixtures/market-prices";
import { seedProPicksRun } from "./fixtures/propicks-run";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

// Guard de regresion (bug d del lote log-hygiene, 2026-10-12).
//
// Contexto: el log de un run e2e del 11/10 mostro un warning de hidratacion
// de React 19 en /propicks sobre el input oculto del Slider Radix
// (SliderBubbleInput): el diff mostraba el SSR con
// style="display:none;caret-color:transparent" y el cliente con
// {display:"none"}.
//
// CAUSA RAIZ PROBADA (12/10, experimento controlado sobre Chromium de
// Playwright 1.64 con about:blank y 4 inputs):
// - page.screenshot() tiene la opcion `caret` con default "hide" (docs
//   oficiales en playwright-core/types/types.d.ts). Su implementacion
//   escribe caret-color:transparent !important INLINE en TODOS los
//   inputs/textareas del documento durante la captura y lo restaura al
//   terminar, desde el mundo aislado de Playwright (por eso no deja stack
//   JS en el mundo principal: 0 setProperty/cssText/setAttribute, pero el
//   MutationObserver si ve la mutacion del atributo).
// - Verificado: idle/click/fill/teclado/foco JS -> 0 mutaciones;
//   screenshot() y screenshot({caret:"hide"}) -> mutacion en los 4 inputs
//   en el mismo ms, restaurada enseguida; screenshot({caret:"initial"}) ->
//   0 mutaciones.
// - En las respuestas OBSERVADAS el HTML SSR salio limpio: 0 ocurrencias
//   de caret-color en la captura cruda de todos los documentos servidos
//   durante una suite completa de 146 tests, ni en curls directos de
//   /research/news y /research/MSFT. Ni el repo, ni Radix 1.3.6, ni los
//   chunks .next contienen ese string.
// - React 19.1 (react-dom-client.development.js, diffHydratedStyles)
//   compara el atributo style crudo contra el estilo cliente serializado
//   SIN canonicalizar CSS, e imprime el diff leyendo la CSSOM VIVA
//   (getStylesObjectFromElement). Si la ventana transitoria del screenshot
//   pisa la hidratacion (dev server cargado en suite = hidratacion lenta),
//   el warning aparece con caret-color atribuido al "servidor" aunque el
//   SSR nunca lo envio. Es dev-only.
// - La variante "display:none" vs "display: none;" del warning original es
//   canonicalizacion CSSOM: falso positivo byte-a-byte del mismo patron
//   descrito en https://github.com/facebook/react/issues/33437 (cerrado
//   como stale, Status: Unconfirmed; se cita como patron conocido, no como
//   prueba).
// - En un navegador real (sin Playwright) su log mostro el mismo
//   warning; el escritor concreto en su maquina NO esta identificado.
//   Hipotesis SIN verificar: una extension u otro actor externo que oculta
//   carets inline siguiendo el mismo patron. Lo probado es que ni el SSR
//   observado ni el codigo del repo escriben caret-color.
//
// Por eso esta spec NO hace screenshots (su browser nunca recibe la
// escritura transitoria) y research-controls-hydration.spec.ts, que si
// mezcla screenshots con una ventana de hidratacion ensanchada, usa
// caret:"initial". El patron "caret-color" se mantiene en la lista: con
// esas dos medidas, su reaparicion indicaria un escritor REAL nuevo.
//
// Este guard monta /propicks CON DATOS (run del embudo sembrado) para que
// los Sliders Radix y sus inputs ocultos esten montados de verdad, y falla
// si reaparece cualquier warning de hidratacion. Si algun dia falla, el
// diff completo queda en el log del test.

test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user";
const apiBase = E2E_UI_BACKEND_URL;

function signedHeaders(method: string, path: string, body: Buffer = Buffer.alloc(0)) {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(body).digest("hex");
  const signature = createHmac("sha256", apiSecret)
    .update(`${apiUser}:${apiUser}:${timestamp}:${nonce}:${method}:${path}:${bodyHash}`)
    .digest("hex");
  return {
    "X-CavaAI-Tenant": apiUser,
    "X-CavaAI-User": apiUser,
    "X-CavaAI-Timestamp": timestamp,
    "X-CavaAI-Nonce": nonce,
    "X-CavaAI-Method": method,
    "X-CavaAI-Path": path,
    "X-CavaAI-Body-Hash": bodyHash,
    "X-CavaAI-Signature": signature,
    "Content-Type": "application/json",
  };
}

async function seedProPicksData(request: import("@playwright/test").APIRequestContext) {
  // Tickers sinteticos exclusivos de esta spec (tenant e2e compartido).
  const tickers = ["E2EPP1", "E2EPP2"];
  // 2 empresas x 2 fechas FIJAS (ancla 2026-09-09): misma regla de
  // convivencia con _common_sessions que portfolio-chart-warnings.spec.ts -
  // sembrar de mas sube la mediana de /movers y expulsa a COST de
  // ticker-badges en runs parciales.
  const days: { date: string; close: number }[] = [];
  for (let i = 2; i >= 1; i--) {
    days.push({
      date: new Date(Date.parse("2026-09-09T00:00:00Z") - (i - 1) * 86400000).toISOString().slice(0, 10),
      close: 100 + i,
    });
  }
  for (const t of tickers) {
    const body = Buffer.from(JSON.stringify({ ticker: t, name: `${t} Inc`, exchange: "NASDAQ", currency: "USD" }));
    const res = await request.post(`${apiBase}/api/companies/ensure`, {
      data: body, headers: signedHeaders("POST", "/api/companies/ensure", body),
    });
    expect(res.status(), await res.text()).toBeLessThan(300);
    seedMarketPrices(t, days);
  }
  const asOf = new Date().toISOString().slice(0, 10);
  seedProPicksRun(apiUser, tickers.map((t, i) => ({ ticker: t, rank: i + 1, score: 90 - i * 5 })), asOf);
}

const HYDRATION_PATTERNS = [
  "An error occurred during hydration",
  "Hydration failed",
  "did not match. Server-rendered HTML",
  "A tree hydrated but some attributes",
  "caret-color",
];

for (const vp of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "movil", width: 390, height: 844 },
]) {
  test(`/propicks con Slider montado sin warnings de hidratacion (${vp.name})`, async ({ page, request }) => {
    await seedProPicksData(request);
    const consoleLines: string[] = [];
    page.on("console", (m) => consoleLines.push(m.text()));
    page.on("pageerror", (e) => consoleLines.push(String(e)));

    // Prueba SSR del componente que originaba el warning: el BubbleInput
    // oculto del Slider Radix (RadioBubbleInput). En Radix 1.3.6 es HERMANO
    // del span role=slider (no descendiente) y SOLO se renderiza cuando
    // isFormControl es true: durante el SSR/primer render siempre, y tras
    // hidratar unicamente si hay <form> ancestro (la pagina no lo tiene, asi
    // que el input puede desaparecer post-hidratacion — no se exige en DOM
    // hidratado porque seria una condicion falsa). Por eso la asercion del
    // input se hace sobre el HTML SSR, que es donde vivia el mismatch del
    // log (style="display:none;caret-color:transparent" servido por SSR).
    const ssrRes = await request.get("/propicks");
    expect(ssrRes.status(), "SSR de /propicks con datos debe responder 200").toBe(200);
    const ssrHtml = await ssrRes.text();
    const ssrSliderThumbs = (ssrHtml.match(/role="slider"/g) || []).length;
    const ssrBubbleInputs = (ssrHtml.match(/<input[^>]*style="display:\s*none"/g) || []).length;
    expect(
      ssrSliderThumbs,
      "el SSR debe incluir los 2 thumbs de los Sliders de los filtros"
    ).toBeGreaterThanOrEqual(2);
    expect(
      ssrBubbleInputs,
      "el SSR debe incluir los 2 BubbleInput ocultos (el elemento del warning original)"
    ).toBeGreaterThanOrEqual(2);

    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto("/propicks", { waitUntil: "networkidle", timeout: 60000 });

    // Tras hidratar: los thumbs siguen montados (el input oculto puede
    // desaparecer sin <form>, ver nota superior — no se exige aqui).
    // Bajo lg los filtros vienen plegados (d0048bee): se abren con su boton
    // real; en desktop el boton no existe y el cuerpo ya esta visible.
    const mostrar = page.getByRole("button", { name: "Mostrar filtros" });
    if (await mostrar.isVisible()) await mostrar.click();
    const sliders = page.getByRole("slider");
    await expect(sliders.first(), "los filtros con Slider Radix deben estar montados (pagina con datos, no ProPicksLoadError)").toBeVisible({ timeout: 30000 });
    const sliderCount = await sliders.count();
    expect(sliderCount, "EnhancedProPicksFilters monta 2 Sliders (score y riesgo)").toBeGreaterThanOrEqual(2);

    // Margen para hidratacion tardia de boundaries Suspense streameados.
    await page.waitForTimeout(4000);

    const hits = consoleLines.filter((l) =>
      HYDRATION_PATTERNS.some((p) => l.includes(p))
    );
    expect(
      hits,
      `warnings de hidratacion en /propicks (${vp.name}, ${sliderCount} thumbs hidratados, SSR ${ssrSliderThumbs} thumbs/${ssrBubbleInputs} inputs):\n${hits.join("\n").slice(0, 2000)}`
    ).toEqual([]);
  });
}
