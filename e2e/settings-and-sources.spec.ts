import { expect, test } from '@playwright/test';

test.skip(process.env.E2E_UI_RUN !== '1', 'Local UI required');

test('settings LLM section exposes the provider form without leaking a key', async ({ page }) => {
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Ajustes', level: 1 })).toBeVisible();
  // Las secciones de ajustes son disclosures nativos (<details>): hay que
  // abrir «Modelo de IA» antes de ver el formulario. Chrome no expone nombre
  // accesible para <details> cuando el <summary> lleva contenido complejo, así
  // que el ancla estable es el id de sección (el mismo que usa la nav interna).
  const section = page.locator('details#llm');
  await expect(section).toBeVisible();
  await section.locator('summary').click();
  const form = page.getByRole('form', { name: 'Configuración del modelo de IA' });
  await expect(form.getByRole('combobox', { name: 'Proveedor' })).toBeVisible();
  await expect(form.getByRole('textbox', { name: 'Modelo', exact: true })).toBeVisible();
  await expect(form.getByLabel('Clave API')).toBeVisible();
  await expect(form.getByRole('button', { name: /Probar conexión/ })).toBeVisible();
  await expect(form.getByRole('button', { name: /Guardar/ })).toBeVisible();
  const html = await page.content();
  expect(html).not.toMatch(/sk-[A-Za-z0-9]{20,}/);
});

test('sources defaults to the followed universe and keeps filters in the URL', async ({ page }) => {
  await page.goto('/research/sources');
  const scope = page.getByLabel('Alcance');
  await expect(scope).toHaveValue('followed');
  await expect(page.locator('#sources-source-type')).toBeVisible();
  await expect(page.locator('#sources-q')).toBeVisible();
  await scope.selectOption('all');
  await page.locator('#sources-q').fill('10-K');
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(page).toHaveURL(/scope=all/);
  await expect(page).toHaveURL(/q=10-K/);
});

test('thesis view renders the paginated research panels', async ({ page }) => {
  await page.goto('/research/MSFT?view=thesis');
  await expect(page.getByRole('heading', { name: 'MSFT', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Historial de versiones y aprobaciones/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Afirmaciones y evidencia' })).toBeVisible();
});
