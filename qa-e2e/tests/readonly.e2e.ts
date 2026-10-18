import { test } from '@e2e-dev/web';
import { expect } from 'e2e';
import { z } from 'zod';

// Pasada de SOLO LECTURA contra produccion, solo paginas publicas (sin login).
const RULES =
  'READ-ONLY. Never create, edit, delete or submit anything except the login form. ' +
  'Do not click buttons that save, add, remove, buy, sell, import, or generate. Only navigate and read.';

// La pasada de agente necesita el proveedor de Zen. El workflow hace un
// precheck real (POST /chat/completions con la misma clave, cabeceras y modelo
// de e2e.config.ts) y exporta E2E_AGENT=1 solo si respondio 200. Con cualquier
// otra cosa (el 403 del free tier de OpenCode, red caida, falta la clave) los
// tests de agente se saltan CON RAZON en el reporte y el run cierra con los
// tests deterministas; el summary del workflow lleva el aviso en cabecera, asi
// que un verde sin agente nunca se presenta como verde limpio.
const SKIP_AGENT: string | false =
  process.env.E2E_AGENT !== '1' &&
  'Pasada de agente NO ejecutada: el precheck del proveedor Zen fallo o falta OPENCODE_API_KEY.';

test('public landing loads', async ({ app, browser }) => {
  await app.open('/');
  await expect(browser.locator('body')).toBeVisible();
});

// Smoke de login DETERMINISTA (Playwright, sin agente): /sign-in tiene que
// servir el formulario completo y sin errores. Sustituye a la version con
// agente, que dejo el workflow en rojo cada deploy desde que el free tier de
// OpenCode empezo a responder 403 fuera de OpenCode. El valor del agente
// (detectar texto sin traducir, solapes, estados rotos) sigue existiendo en el
// describe de abajo, solo cuando el precheck confirma que el proveedor vive.
test('login page is reachable and clean', async ({ app, browser }) => {
  await app.open('/');
  await app.open('/sign-in');
  // El H1 propio del formulario (no la pagina de error de Next ni un 500).
  await expect(browser.locator('h1.form-title')).toContainText('Bienvenido de nuevo');
  // Formulario completo: email, password y el submit de react-hook-form.
  await expect(browser.locator('input[name="email"]')).toBeVisible();
  await expect(browser.locator('input[name="password"]')).toBeVisible();
  await expect(browser.locator('button[type="submit"]')).toBeVisible();
  // Sin errores visibles: ni errores de validacion (role="alert" en
  // InputField) ni toasts de error de sonner. Se lee el DOM de la pagina con
  // evaluate y no con el locator del engine: el engine inyecta su propia
  // mascara de campos [secure] sobre el input de password y sus locators la
  // cuentan (observado: count 1 con la pagina limpia).
  const erroresVisibles = await browser.evaluate(() => {
    const visible = (e: Element) => !!(e as HTMLElement).offsetParent;
    const alerts = Array.from(document.querySelectorAll('[role="alert"]'))
      .filter((e) => visible(e) && (e.textContent ?? '').trim().length > 0)
      .map((e) => (e.textContent ?? '').trim().slice(0, 80));
    const toasts = Array.from(document.querySelectorAll('[data-sonner-toast][data-type="error"]'))
      .filter(visible)
      .map((e) => (e.textContent ?? '').trim().slice(0, 80));
    return { alerts, toasts };
  });
  if (erroresVisibles.alerts.length || erroresVisibles.toasts.length) {
    throw new Error(`/sign-in muestra errores: ${JSON.stringify(erroresVisibles)}`);
  }
});

test.describe('pasada de agente (proveedor Zen)', { skip: SKIP_AGENT }, () => {
  test('login page has no visible UI problems', async ({ app, agent }) => {
    await app.open('/');
    await agent.act(`${RULES} Find and open the login or sign-in page. Do not type anything.`);
    await agent.assert('a login form or sign-in prompt is visible with no error banner');
    const info = await agent.extract(
      'List visible UI problems on this page: error messages, untranslated English text, overlapping or cut-off elements. Answer as JSON with exactly two keys: "checked" (the boolean true) and "problems" (an array of short strings, empty if clean).',
      { schema: z.object({ checked: z.literal(true), problems: z.array(z.string()) }) },
    );
    console.log('[login]', JSON.stringify(info.problems.length ? info.problems : 'ninguno'));
  });
});
