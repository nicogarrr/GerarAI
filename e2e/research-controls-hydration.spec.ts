import { createHash, createHmac, randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { E2E_UI_BACKEND_URL } from "./fixtures/e2e-env";

test.skip(process.env.E2E_UI_RUN !== '1', 'UI harness required');
test('research controls cannot accept input before their client handlers exist', async ({ page, request }) => {
  const path = '/api/companies/ensure';
  const body = JSON.stringify({ ticker: 'MSFT', name: 'Microsoft Corporation' });
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomUUID().replaceAll('-', '');
  const hash = createHash('sha256').update(body).digest('hex');
  const secret = process.env.RESEARCH_AUTH_SECRET ?? 'cavaai-e2e-research-secret-at-least-32-characters';
  const signature = createHmac('sha256', secret)
    .update(`e2e-api-tenant:e2e-api-user:${timestamp}:${nonce}:POST:${path}:${hash}`).digest('hex');
  const response = await request.post(`${E2E_UI_BACKEND_URL}${path}`, {
    data: body, headers: {
      'Content-Type': 'application/json', 'X-CavaAI-Tenant': 'e2e-api-tenant', 'X-CavaAI-User': 'e2e-api-user',
      'X-CavaAI-Timestamp': timestamp, 'X-CavaAI-Nonce': nonce, 'X-CavaAI-Method': 'POST',
      'X-CavaAI-Path': path, 'X-CavaAI-Body-Hash': hash, 'X-CavaAI-Signature': signature,
    },
  });
  expect(response.ok()).toBeTruthy();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/_next/static/**/*.js*', async (route) => {
    await gate;
    await route.continue();
  });
  try {
    await page.goto('/research/MSFT?view=thesis', { waitUntil: 'commit' });
    const history = page.getByRole('button', { name: 'Historial de versiones y aprobaciones', includeHidden: true });
    const trigger = page.getByRole('button', { name: 'Alerta de precio' });
    await expect(history).toBeDisabled();
    // El formulario de alerta vive en un popover (Radix): antes de hidratar
    // el botón campana no abre nada y "+ Alerta" queda inaccesible.
    await trigger.click();
    await expect(page.getByRole('button', { name: '+ Alerta', exact: true })).toBeHidden();
    release();
    await page.waitForLoadState('load', { timeout: 60_000 });
    await expect(history).toBeEnabled();
    await trigger.click();
    const alert = page.getByRole('button', { name: '+ Alerta', exact: true });
    await expect(alert).toBeEnabled();
    if ((page.viewportSize()?.width ?? 1440) < 768) {
      await history.click();
      await expect(history).toHaveAttribute('aria-expanded', 'true');
    }
    await alert.click();
    await expect(page.getByText('Introduce un precio objetivo válido', { exact: true })).toBeVisible();
    // caret: "initial": el default de Playwright (caret:"hide") escribe
    // caret-color:transparent !important INLINE y transitorio en TODOS los
    // inputs durante la captura (causa raiz probada del falso warning de
    // hidratacion caret-color, 12/10); en esta spec, que retrasa los chunks
    // JS para ensanchar la ventana de hidratacion, esa escritura podria
    // solaparse con el chequeo de estilos de React 19. caret:"initial"
    // desactiva la escritura.
    await page.screenshot({ path: `test-results/hydration-controls-${page.viewportSize()?.width}.png`, fullPage: true, caret: "initial" });
  } finally {
    release();
  }
});
