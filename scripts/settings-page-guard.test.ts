/**
 * Ajustes: datos fiscales, modelo de IA con clave propia y Telegram.
 * La API key jamas se renderiza desde el servidor: solo el last4.
 * Ejecucion: node --experimental-strip-types --test scripts/settings-page-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path: string) => readFileSync(path, 'utf8');

describe('ajustes', () => {
  const route = read('app/(root)/settings/page.tsx');
  const page = read('components/settings/SettingsContent.tsx');
  const form = read('components/settings/TaxDeclarantForm.tsx');
  const llmForm = read('components/settings/LlmSettingsForm.tsx');
  const llmAction = read('lib/actions/llm-settings.actions.ts');
  it('la pagina ofrece datos fiscales, modelo de IA y Telegram', () => {
    assert.match(route, /requireAuthenticatedUser/);
    assert.match(route, /SettingsContent/);
    assert.ok(page.includes("title={t('settings.tax.title')}"));
    assert.ok(page.includes("title={t('settings.llm.title')}"));
    for (const [locale, tax, llm] of [['es', 'Datos fiscales del declarante', 'Modelo de IA'], ['en', 'Declarant tax details', 'AI model']]) {
      const messages = JSON.parse(read(`lib/i18n/messages/${locale}/settings.json`));
      assert.equal(messages.tax.title, tax);
      assert.equal(messages.llm.title, llm);
    }
    assert.match(page, /id="llm"/);
    assert.match(page, /LlmSettingsForm/);
    assert.match(page, /href="\/alerts"/);
    assert.doesNotMatch(page, /getResearchSettings|Conectores|Presupuesto|Entorno de ejecuci/);
  });
  it('el formulario guarda lo que lee el Modelo 720', () => {
    for (const key of ['apellidos_nombre', 'nif', 'numero_declaracion', 'telefono']) {
      assert.match(form, new RegExp(`'${key}'`));
    }
    assert.match(form, /filed_720_before/);
    assert.match(form, /custody/);
    assert.match(form, /custody_entities/);
    assert.match(form, /first_acquisition_dates/);
    assert.match(form, /saveTaxDeclarant/);
  });
  it('el formulario LLM nunca pinta la clave del servidor', () => {
    assert.match(llmForm, /saveLlmSettings/);
    assert.match(llmForm, /testLlmConnection/);
    assert.match(llmForm, /api_key_last4/);
    assert.match(llmForm, /type="password"/);
    assert.doesNotMatch(llmForm, /initial\.api_key\b/);
    assert.doesNotMatch(llmForm, /defaultValue=\{[^}]*api[_-]?key/i);
    assert.ok(llmForm.includes("t('settings.llm.paidNote')"));
    for (const [locale, paid] of [['es', /Los proveedores de pago los paga el usuario/], ['en', /Paid providers are paid by the user/]] as const) {
      assert.match(JSON.parse(read(`lib/i18n/messages/${locale}/settings.json`)).llm.paidNote, paid);
    }
    assert.match(llmForm, /href="\/privacidad"/);
  });
  it('la accion solo devuelve la vista del backend (sin clave)', () => {
    assert.match(llmAction, /researchRequest<LlmSettings>\('\/api\/settings\/llm'/);
    assert.match(llmAction, /api_key_last4/);
    assert.doesNotMatch(llmAction, /api_key:\s*string;\s*\n\s*api_key_last4/);
  });
  it('el menu del avatar enlaza a /settings, al bloque LLM y el enlace antiguo redirige', () => {
    const dropdown = read('components/UserDropdown.tsx');
    assert.match(dropdown, /router\.push\("\/settings"\)/);
    assert.match(dropdown, /router\.push\("\/settings#llm"\)/);
    assert.match(dropdown, /t\('shell.user.aiModel'\)/);
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/shell.json', 'utf8')).user.aiModel, 'Modelo de IA');
    assert.match(read('next.config.ts'), /source: '\/research\/settings', destination: '\/settings'/);
  });
});
