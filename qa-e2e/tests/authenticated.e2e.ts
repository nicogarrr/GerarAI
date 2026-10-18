import { test } from '@e2e-dev/web';
import { z } from 'zod';

// Pasada de SOLO LECTURA con la cuenta que indiquen los secrets (la cuenta indicada, con autorizacion).
// Las credenciales llegan por secrets del repo (E2E_USER_EMAIL / E2E_USER_PASSWORD),
// nunca estan en el codigo ni en los logs. Sin ellas, el fichero se salta de forma
// explicita (el resumen lo dice) en vez de pasar en verde sin haber mirado nada.
const EMAIL = process.env.E2E_USER_EMAIL ?? '';
const PASSWORD = process.env.E2E_USER_PASSWORD ?? '';
// El login es una server action de Next: hace POST a la propia ruta /sign-in.
const LOGIN_PATH = '/sign-in';

const RULES =
  'READ-ONLY. Only navigate, click tabs and read. Never create, edit, delete, import, ' +
  'save, buy, sell, generate or submit anything. Never open the user menu or click Cerrar sesion / Logout. Never click buttons named like Add, ' +
  'Remove, Delete, Save, Sync, Import, Upload, Create, Generate, Buy or Sell.';

const FINDINGS = z.object({
  checked: z.literal(true),
  problems: z.array(z.string()),
});

const REPORT =
  'Report visible UI problems on the screen as JSON with exactly two keys: "checked" ' +
  '(the boolean true) and "problems" (array of short strings, empty if clean). A problem is: ' +
  'an error banner, a stuck loading state, untranslated English text in the Spanish UI, ' +
  'a value shown without currency or unit, an empty state that hides a failed load, ' +
  'text cut off or overlapping, or "Fecha desconocida" / "SIN DATOS" / "N/D" where a value is expected.';

// e2e v0.15: test.skip(condicion, razon) fuera de un test es COLLECTION_ERROR.
// El skip a nivel de describe (capa) es la forma soportada y deja constancia de
// la razon en el reporte en vez de un verde falso.
const SKIP_AUTH: string | false =
  (!EMAIL || !PASSWORD) && 'Faltan los secrets E2E_USER_EMAIL / E2E_USER_PASSWORD: no se ejecuta.';

// Mismo criterio que readonly.e2e.ts: la pasada de agente solo corre cuando el
// precheck del workflow confirmo que el proveedor Zen responde (E2E_AGENT=1).
// El bloqueo mecanico de escritura y el login son deterministas y corren
// siempre que haya credenciales, con o sin agente.
const SKIP_AGENT: string | false =
  process.env.E2E_AGENT !== '1' &&
  'Pasada de agente NO ejecutada: el precheck del proveedor Zen fallo o falta OPENCODE_API_KEY.';

test.describe('rutas autenticadas (solo lectura)', { skip: SKIP_AUTH }, () => {

  test.beforeEach(async ({ app, browser }) => {
    // BLOQUEO MECANICO de escritura (la sesion es una cuenta real contra
    // produccion): todo metodo distinto de GET/HEAD/OPTIONS se aborta en el
    // contexto del navegador, salvo el POST del login. Un clic destructivo del
    // agente falla aunque lo intente; el prompt de solo lectura es la segunda capa.
    await browser.route('**/*', async (route) => {
      const req = route.request;
      const method = req.method.toUpperCase();
      const path = new URL(req.url).pathname;
      const isLogin = method === 'POST' && path === LOGIN_PATH;
      if (['GET', 'HEAD', 'OPTIONS'].includes(method) || isLogin) {
        await route.continue();
        return;
      }
      console.log(`[bloqueado] ${method} ${path}`);
      await route.abort();
    });
    await app.open('/sign-in');
    await browser.locator('input[name="email"]').fill(EMAIL);
    await browser.locator('input[name="password"]').fill(PASSWORD);
    await browser.locator('button[type="submit"]').click();
    await browser.waitForURL(/^(?!.*\/sign-in).*$/, { timeout: 30_000 });
  });

  // Prueba controlada del bloqueo: POST/PUT/PATCH/DELETE a una ruta que no existe. Si el
  // bloqueo funciona, fetch falla en el navegador; si no, el servidor respondera 404
  // (sin efecto). Debe quedar bloqueado en cada run.
  test('el bloqueo de escritura aborta POST, PUT, PATCH y DELETE', async ({ browser }) => {
    const results = await browser.evaluate(async () => {
      const out: Record<string, string> = {};
      for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
        try {
          const r = await fetch('/api/qa-write-probe', { method });
          out[method] = `pasa:${r.status}`;
        } catch {
          out[method] = 'bloqueado';
        }
      }
      return out;
    });
    console.log('[bloqueo-escritura]', JSON.stringify(results));
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      if (results[method] !== 'bloqueado') throw new Error(`${method} NO fue bloqueado: ${results[method]}`);
    }
  });

  const scenarios: Array<{ tag: string; path: string; task: string }> = [
    {
      tag: 'cartera',
      path: '/portfolio',
      task: 'Open every tab of the portfolio page one by one (click each tab, wait for it to load). Also check that amounts show a currency consistently (EUR vs US$).',
    },
    {
      tag: 'research',
      path: '/research',
      task: 'Open the research page for AAPL, then open every tab and the Modelo (valuation model) section, scrolling to read each one.',
    },
    { tag: 'propicks', path: '/propicks', task: 'Read the page and open every visible tab or card detail without saving anything.' },
    { tag: 'inteligencia', path: '/portfolio/intelligence', task: 'Read the page and open every tab.' },
    { tag: 'conocimiento', path: '/knowledge', task: 'Read the page, open every tab, and then open the Grafo (knowledge graph) page.' },
    { tag: 'noticias', path: '/research/news', task: 'Read the news list and open one item detail if available. Check dates and the ticker each item is attached to.' },
    { tag: 'watchlist', path: '/watchlist', task: 'Read the watchlist rows and check dates and N/D values.' },
  ];

  test.describe('pasada de agente (proveedor Zen)', { skip: SKIP_AGENT }, () => {
    for (const s of scenarios) {
      test(`${s.tag}: navega pestanas y detecta problemas`, async ({ app, agent }) => {
        await app.open(s.path);
        await agent.act(`${RULES} ${s.task}`);
        await agent.assert('the page is not showing a crash, a blank screen or an unhandled error', { screenshot: false });
        const info = await agent.extract(REPORT, { schema: FINDINGS });
        console.log(`[${s.tag}]`, JSON.stringify(info.problems.length ? info.problems : 'ninguno'));
      });
    }
  });
});
