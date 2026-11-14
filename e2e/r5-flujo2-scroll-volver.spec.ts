import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

/**
 * Recorrido real (auditoría de flujo r5, 11-nov): se baja por la ficha en la
 * pestaña Valoración, se pulsa el enlace al Informe del contenido y se
 * vuelve. Medido en un `next build` a 1440 px (NVDA): desde 1600 px, el atrás
 * del navegador dejaba la ficha en 2469 px. Ahora se vuelve a la posición del
 * usuario (o al tope si la página ya no llega).
 */
const runUiE2E = process.env.E2E_UI_RUN === "1";
const apiSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const apiUser = "e2e-browser-user";

function signedHeaders(method: string, path: string, body: Buffer) {
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

async function post(request: APIRequestContext, path: string, payload: unknown) {
  const body = Buffer.from(JSON.stringify(payload));
  const res = await request.post(`${E2E_UI_BACKEND_URL}${path}`, { data: body, headers: signedHeaders("POST", path, body) });
  expect(res.status(), await res.text()).toBeLessThan(300);
}

/**
 * Baja por la ficha hasta el enlace al Informe del contenido (no el del menú
 * «Más acciones», que está arriba) y devuelve el scroll desde el que se pulsa.
 */
async function scrollToContentReportLink(page: Page) {
  const link = page.locator('main a[href$="/informe"]').first();
  await link.scrollIntoViewIfNeeded();
  await page.mouse.move(200, 300);
  await page.mouse.wheel(0, 120);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  let last = -1;
  await expect.poll(async () => {
    const y = await page.evaluate(() => Math.round(window.scrollY));
    const settled = y === last;
    last = y;
    return settled;
  }).toBe(true);
  await link.scrollIntoViewIfNeeded();
  return { link, before: await page.evaluate(() => Math.round(window.scrollY)) };
}

/** La posición vuelve a la del usuario (o al tope si la página es más corta). */
async function expectBackAt(
  page: Page,
  before: number,
  opts?: { t0?: number; note?: () => string },
) {
  // Telemetría para los rojos intermitentes de CI. El sampler de 200 ms es
  // INDEPENDIENTE del poll del gate: este conserva los intervalos por
  // defecto de Playwright, así que lo que el test exige no cambia; la serie
  // solo se enseña si el gate falla (Error en texto, no artefacto).
  // t = 0 es el popstate de la vuelta cuando se pudo marcar (el restore
  // arranca en el commit siguiente); si no, la entrada aquí, justo tras
  // waitForURL. Con eso la serie data mesetas >= 4 s sin crecimiento y
  // crecimientos tardíos, la firma del give-up por sinceGrowthMs.
  const t0 = opts?.t0 ?? Date.now();
  const samples: string[] = [];
  let sampling = true;
  const samplerStart = Date.now();
  const sampler = (async () => {
    while (sampling) {
      try {
        const { y, max } = await page.evaluate(() => ({
          y: Math.round(window.scrollY),
          max: Math.round(document.documentElement.scrollHeight - window.innerHeight),
        }));
        samples.push(`${Date.now() - t0}ms y=${y} max=${max}`);
      } catch {
        break; // página destruida: telemetría best-effort, no es el fallo
      }
      // Denso (50 ms) el primer medio segundo: ahí se ve si y llegó a
      // asentarse en el objetivo antes del primer estirón (restore 'done'
      // precoz) o si nunca pasó por él (restore que no arrancó).
      await new Promise((resolve) => setTimeout(resolve, Date.now() - samplerStart < 600 ? 50 : 200));
    }
  })();
  try {
    await expect.poll(async () => {
      const { y, max } = await page.evaluate(() => ({
        y: Math.round(window.scrollY),
        max: Math.round(document.documentElement.scrollHeight - window.innerHeight),
      }));
      return Math.abs(y - Math.min(before, max)) <= 2 && y > 0;
    }, { timeout: 15_000, message: `scroll esperado ≈ ${before}px` }).toBe(true);
  } catch (cause) {
    // Best-effort: una página cerrada no puede tapar el fallo original.
    let navType = "?";
    try {
      navType = (await page.evaluate(() =>
        (performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined)?.type
      )) ?? "?";
    } catch {
      // sin la página no hay navigation.type; la serie y el cause mandan
    }
    // Memoria de scroll del producto (clave de lib/nav/scroll-memory): el
    // valor ACTUAL para esta URL al fallar, que puede haberse movido desde
    // el target inicial (ver memAntes en la nota del test).
    let mem = "?";
    try {
      mem = await readScrollMemoryFor(page, ""); // "" = URL actual
    } catch {
      // sin la página no hay memoria; la serie y el cause mandan
    }
    // scrollTo programáticos grabados desde la vuelta. Interpretación con
    // cuidado: restoreStep NO llama scrollTo cuando ya está a <=1px del
    // objetivo, así que un log vacío no prueba que el restore no arrancara,
    // y el cese de llamadas no prueba 'done' (puede ser give-up o cancel).
    // El log sí fija: qué valores se aplicaron, desde qué posición y hasta
    // cuándo hubo actividad de window.scrollTo.
    let scrollLog = "?";
    try {
      const log = await page.evaluate(() =>
        (window as unknown as { __r5ScrollLog?: Array<{ t: number; d: string }> }).__r5ScrollLog
      );
      scrollLog = !log
        ? "(sin grabador: la vuelta fue carga de documento)"
        : log.length === 0
          ? "(sin scrollTo)"
          : log.map((e) => `${e.t - t0}ms ${e.d}`).join(" | ");
    } catch {
      // sin la página no hay grabador
    }
    throw new Error(
      `scroll esperado ≈ ${before}px; navigation.type=${navType}; memoria: ${mem}${opts?.note ? `; ${opts.note()}` : ""}; scrollTo: ${scrollLog}; serie: ${samples.join(" | ")}`,
      { cause },
    );
  } finally {
    sampling = false;
    await sampler;
  }
}

/** Descripción corta de la memoria de scroll del producto para `urlKey`
 *  ("" = la URL actual de la página). Best-effort: nunca tapa el fallo. */
async function readScrollMemoryFor(page: Page, urlKey: string): Promise<string> {
  try {
    return await page.evaluate(([key, url]) => {
      try {
        const raw = window.sessionStorage.getItem(key);
        if (!raw) return "vacía";
        const parsed = JSON.parse(raw) as Record<string, number>;
        const here = url || window.location.pathname + window.location.search;
        return `${here}=${parsed[here] ?? "ausente"} (${Object.keys(parsed).length} entradas)`;
      } catch {
        return "ilegible";
      }
    }, ["gerarai:scroll-memory:v1", urlKey] as const);
  } catch {
    return "?";
  }
}

/** Graba las llamadas a window.scrollTo con su instante. Limitaciones
 *  declaradas: solo ve window.scrollTo (no window.scroll/scrollBy,
 *  scrollIntoView ni los ajustes nativos de anchoring); reemplaza la
 *  identidad de window.scrollTo y no se restaura al terminar el test; cada
 *  llamada grabada añade un Date.now y un push, y la lectura al fallar es
 *  un roundtrip más: sonda de diagnóstico que PERTURBA el timing, no una
 *  observación neutra. El parche vive en el documento: si la vuelta es
 *  carga completa el log falta y navigation.type=back_forward lo delata. */
async function recordScrollTo(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __r5ScrollLog?: Array<{ t: number; d: string }> };
    w.__r5ScrollLog = [];
    const orig = window.scrollTo.bind(window) as (...args: unknown[]) => void;
    const patched = (...args: unknown[]) => {
      const first = args[0];
      const d = typeof first === "object" && first !== null
        ? `top=${Math.round((first as ScrollToOptions).top ?? -1)}`
        : `y=${Math.round(Number(args[1]))}`;
      w.__r5ScrollLog!.push({ t: Date.now(), d: `${d} desde=${Math.round(window.scrollY)}` });
      if (w.__r5ScrollLog!.length > 300) w.__r5ScrollLog!.shift();
      orig(...args);
    };
    window.scrollTo = patched as unknown as typeof window.scrollTo;
  });
}

/** Marca el instante del popstate para datar la serie del restore. */
async function markPopstateClock(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __r5PopAt?: number };
    w.__r5PopAt = 0;
    window.addEventListener("popstate", () => { w.__r5PopAt = Date.now(); });
  });
}

/** Lee la marca del popstate (no sobrevive a una carga de documento). */
async function readPopstateClock(page: Page): Promise<number | undefined> {
  try {
    const t = await page.evaluate(() => (window as unknown as { __r5PopAt?: number }).__r5PopAt);
    return t && t > 0 ? t : undefined;
  } catch {
    return undefined;
  }
}

/** Observa si la navegación hacia `urlRe` fue carga de documento (clic
 *  pre-hidratación) en vez de SPA; se reporta en la telemetría del fallo. */
function watchDocumentNav(page: Page, urlRe: RegExp) {
  const state = { seen: false };
  page.on("request", (req) => {
    if (req.resourceType() === "document" && urlRe.test(req.url())) state.seen = true;
  });
  return state;
}

for (const [label, viewport] of [["móvil 390", { width: 390, height: 844 }], ["PC 1440", { width: 1440, height: 900 }]] as const) {
  test.describe(`scroll al volver a la ficha (${label})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");
    test.use({ viewport });

    test.beforeEach(async ({ request }) => {
      await post(request, "/api/companies/ensure", { ticker: "MSFT", name: "Microsoft" });
    });

    test("atrás del navegador desde el Informe vuelve a donde estabas", async ({ page }) => {
      await page.goto("/research/MSFT?view=valoracion");
      await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
      const { link, before } = await scrollToContentReportLink(page);
      expect(before).toBeGreaterThan(0);
      // Tipo de la navegación de ida: un request «document» al informe
      // delataría un clic pre-hidratación (carga completa en vez de SPA).
      // Solo telemetría: no cambia los criterios del test.
      const informeDocNav = watchDocumentNav(page, /\/informe/);
      await link.click();
      await page.waitForURL(/\/research\/MSFT\/informe/);
      await expect(page.locator("h1").first()).toBeVisible();
      // Lectura previa de la memoria antes de la vuelta: referencia del
      // valor que el restore probablemente leerá (algo podría escribir
      // entre medias; no es una observación dentro del restore). Y grabador
      // de window.scrollTo (ver sus limitaciones en recordScrollTo).
      const memAntes = await readScrollMemoryFor(page, "/research/MSFT?view=valoracion");
      await recordScrollTo(page);
      await markPopstateClock(page);
      await page.goBack();
      await page.waitForURL(/\/research\/MSFT\?view=valoracion/);
      const t0 = await readPopstateClock(page);
      await expectBackAt(page, before, { t0, note: () => `docNavIda=${informeDocNav.seen}; memAntes: ${memAntes}` });
    });

    test("«← Volver a la ficha» del Informe vuelve a la pestaña y a donde estabas", async ({ page }) => {
      await page.goto("/research/MSFT?view=valoracion");
      await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
      const { link, before } = await scrollToContentReportLink(page);
      const informeDocNav = watchDocumentNav(page, /\/informe/);
      await link.click();
      await page.waitForURL(/\/research\/MSFT\/informe/);
      const back = page.getByRole("link", { name: "← Volver a la ficha" });
      await expect(back).toHaveAttribute("data-back-mode", "history");
      // Igual que en el test hermano: lectura previa de referencia (no
      // observación dentro del restore) y grabador de window.scrollTo.
      const memAntes = await readScrollMemoryFor(page, "/research/MSFT?view=valoracion");
      await recordScrollTo(page);
      await markPopstateClock(page);
      await back.click();
      await page.waitForURL(/\/research\/MSFT\?view=valoracion/);
      const t0 = await readPopstateClock(page);
      await expectBackAt(page, before, { t0, note: () => `docNavIda=${informeDocNav.seen}; memAntes: ${memAntes}` });
    });
  });
}
