import { expect, test as base } from "@playwright/test";
import type { Page, Request, Response } from "@playwright/test";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { E2E_UI_BACKEND_URL } from "../fixtures/e2e-env";

/**
 * Suite de flujos de usuario (E2E_UI_RUN=1): navegador real contra la app
 * local (Next dev + data-engine APP_ENV=test con el bypass de auth E2E).
 *
 * Cada test lleva un `health` que vigila la página entera mientras dura:
 * errores de consola, excepciones no capturadas y respuestas 4xx/5xx
 * inesperadas. `expectHealthyPage()` añade las comprobaciones visuales:
 * sin desborde horizontal y sin NaN/undefined/null/Infinity/[object Object]
 * visibles. Un hallazgo hace fallar el test con la lista completa.
 */

export const VIEWPORTS = [
  { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
  {
    name: "mobile",
    use: { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true },
  },
] as const;

// Fuera del job bloqueante «Browser E2E» (que corre todo e2e/): esta suite
// solo corre con E2E_USER_FLOWS=1, en su job propio no bloqueante.
export const runUiE2E = process.env.E2E_UI_RUN === "1" && process.env.E2E_USER_FLOWS === "1";

/** Ruido de entorno que no es un fallo de la app (documentado caso a caso). */
const ENV_NOISE: RegExp[] = [
  // Next dev reenvía al navegador los console.error del servidor. Sin claves
  // de proveedores (CI y local) las noticias de Finnhub avisan así; en
  // producción ese log se queda en el servidor.
  /API key is not configured/i,
  // HMR / Fast Refresh de Next dev.
  /\[HMR\]|\[Fast Refresh\]|webpack-hmr|_next\/webpack-hmr/,
  // Aviso de React DevTools en modo desarrollo.
  /Download the React DevTools/,
];

type Issue = string;

export class PageHealth {
  readonly issues: Issue[] = [];
  private readonly allowed: Array<{ status?: number; url: RegExp }> = [];
  private readonly allowedConsole: RegExp[] = [];

  constructor(private readonly page: Page) {
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      if (ENV_NOISE.some((re) => re.test(text))) return;
      if (this.allowedConsole.some((re) => re.test(text))) return;
      // El navegador registra cada 4xx/5xx como "Failed to load resource";
      // la respuesta ya se juzga (con su URL) en el listener de respuestas.
      if (/Failed to load resource: the server responded with a status of/.test(text)) return;
      this.issues.push(`console.error: ${text.slice(0, 400)}`);
    });
    page.on("pageerror", (err) => {
      this.issues.push(`pageerror: ${String(err).slice(0, 400)}`);
    });
    page.on("response", (res: Response) => {
      const status = res.status();
      if (status < 400) return;
      const url = res.url();
      if (this.allowed.some((a) => (a.status === undefined || a.status === status) && a.url.test(url))) return;
      this.issues.push(`http ${status} ${res.request().method()} ${url.slice(0, 200)}`);
    });
    page.on("requestfailed", (req: Request) => {
      const failure = req.failure()?.errorText ?? "";
      // Navegaciones y fetch cancelados por el propio cambio de página.
      if (/ERR_ABORTED|NS_BINDING_ABORTED|cancelled/i.test(failure)) return;
      this.issues.push(`requestfailed ${req.method()} ${req.url().slice(0, 200)} ${failure}`);
    });
  }

  /** Respuesta >= 400 esperada por el propio flujo (p. ej. la página 404). */
  allowResponse(url: RegExp, status?: number) {
    this.allowed.push({ url, status });
  }

  allowConsole(re: RegExp) {
    this.allowedConsole.push(re);
  }

  assertClean() {
    expect(this.issues, "salud de la página (consola, red, excepciones)").toEqual([]);
  }
}

const BAD_TOKENS = /(?:^|[^\p{L}\p{N}_])(NaN|undefined|null|-?Infinity|\[object Object\])(?![\p{L}\p{N}_])/u;

/** Comprobaciones visuales sobre lo que ve el usuario ahora mismo. */
export async function expectHealthyPage(page: Page, context = "") {
  const report = await page.evaluate((src) => {
    const re = new RegExp(src, "u");
    const text = document.body.innerText;
    const bad: string[] = [];
    for (const line of text.split("\n")) {
      const m = line.match(re);
      if (m) bad.push(line.trim().slice(0, 160));
      if (bad.length > 5) break;
    }
    const doc = document.documentElement;
    const overflow = doc.scrollWidth - doc.clientWidth;
    const wide: string[] = [];
    if (overflow > 1) {
      for (const el of Array.from(document.querySelectorAll("body *"))) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.right > doc.clientWidth + 1) {
          wide.push(`${el.tagName.toLowerCase()}.${String((el as HTMLElement).className).slice(0, 80)} right=${Math.round(r.right)}`);
          if (wide.length > 4) break;
        }
      }
    }
    return { bad, overflow, wide, length: text.trim().length };
  }, BAD_TOKENS.source);
  const where = context ? ` (${context})` : "";
  expect(report.bad, `texto roto visible${where}`).toEqual([]);
  expect(report.overflow, `desborde horizontal${where}: ${report.wide.join(" | ")}`).toBeLessThanOrEqual(1);
  expect(report.length, `página sin contenido${where}`).toBeGreaterThan(20);
}

/** Navega y espera a que la página esté quieta (sin red ni hidratación pendiente). */
export async function visit(page: Page, path: string) {
  let response;
  try {
    response = await page.goto(path, { waitUntil: "domcontentloaded" });
  } catch (err) {
    // `next dev` puede abortar una navegación mientras recompila (ERR_ABORTED).
    // Un reintento: si la app falla de verdad, el segundo intento lo dirá.
    if (!/ERR_ABORTED|NS_BINDING_ABORTED/.test(String(err))) throw err;
    response = await page.goto(path, { waitUntil: "domcontentloaded" });
  }
  await page.waitForLoadState("networkidle", { timeout: 45_000 }).catch(() => undefined);
  return response;
}

export const test = base.extend<{ health: PageHealth }>({
  // auto: vigila TODOS los tests aunque no pidan `health` explícitamente.
  health: [
    async ({ page }, provide) => {
      const health = new PageHealth(page);
      await provide(health);
      health.assertClean();
    },
    { auto: true },
  ],
});

export { expect };

// ---------------------------------------------------------------------------
// Backend firmado como el usuario del bypass E2E (e2e-browser-user), solo para
// preparar/limpiar estado. Los flujos en sí van siempre por la UI.

const backendURL = E2E_UI_BACKEND_URL;
const secret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const browserUser = "e2e-browser-user";

export async function backendCall(method: string, path: string, body?: unknown) {
  // The auth bridge signs the pathname, never query parameters.
  const signedPath = new URL(path, backendURL).pathname;
  const payload = body === undefined ? Buffer.alloc(0) : Buffer.from(JSON.stringify(body));
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll("-", "");
  const bodyHash = createHash("sha256").update(payload).digest("hex");
  const signature = createHmac("sha256", secret)
    .update(`${browserUser}:${browserUser}:${timestamp}:${nonce}:${method}:${signedPath}:${bodyHash}`)
    .digest("hex");
  const res = await fetch(backendURL + path, {
    method,
    body: body === undefined ? undefined : payload,
    headers: {
      "Content-Type": "application/json",
      "X-CavaAI-Tenant": browserUser,
      "X-CavaAI-User": browserUser,
      "X-CavaAI-Timestamp": timestamp,
      "X-CavaAI-Nonce": nonce,
      "X-CavaAI-Method": method,
      "X-CavaAI-Path": signedPath,
      "X-CavaAI-Body-Hash": bodyHash,
      "X-CavaAI-Signature": signature,
    },
  });
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = text;
  }
  return { status: res.status, json };
}

/** Full paginated transaction list for the isolated E2E tenant. */
export async function backendTransactions() {
  const { readTransactions } = await import('../../scripts/e2e-transactions');
  return readTransactions(backendCall);
}
