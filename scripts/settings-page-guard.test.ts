/**
 * Ajustes: solo datos fiscales editables y enlace a Telegram; el menú del avatar
 * y la redirección del enlace antiguo apuntan a /settings.
 * Ejecución: node --experimental-strip-types --test scripts/settings-page-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path: string) => readFileSync(path, 'utf8');

describe('ajustes', () => {
  const page = read('app/(root)/settings/page.tsx');
  const form = read('components/settings/TaxDeclarantForm.tsx');
  it('la página solo ofrece datos fiscales y Telegram', () => {
    assert.match(page, /Datos fiscales del declarante/);
    assert.match(page, /href="\/alerts"/);
    assert.doesNotMatch(page, /getResearchSettings|Conectores|Presupuesto|Entorno de ejecución/);
  });
  it('el formulario guarda lo que lee el Modelo 720', () => {
    for (const key of ['apellidos_nombre', 'nif', 'numero_declaracion', 'telefono']) {
      assert.match(form, new RegExp(`'${key}'`));
    }
    assert.match(form, /filed_720_before/);
    assert.match(form, /custody/);
    assert.match(form, /saveTaxDeclarant/);
  });
  it('el menú del avatar enlaza a /settings y el enlace antiguo redirige', () => {
    assert.match(read('components/UserDropdown.tsx'), /router\.push\("\/settings"\)/);
    assert.match(read('next.config.ts'), /source: '\/research\/settings', destination: '\/settings'/);
  });
});
