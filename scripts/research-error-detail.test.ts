/**
 * Los 422 de validación del motor (detail = lista de objetos) no pueden
 * llegar a la UI como «[object Object]». Ejecución:
 *   node --experimental-strip-types --test scripts/research-error-detail.test.ts
 */
import { describe, it, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

register('./research-client-contract.loader.mjs', import.meta.url);

// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
const { researchErrorDetail } = await import('../lib/research/error-detail.ts');
// @ts-expect-error TS5097: la extension explicita la exige node --experimental-strip-types.
const { researchRequest } = await import('../lib/research/client.ts');

const FALLBACK = '422 Unprocessable Entity';

describe('researchErrorDetail', () => {
  it('un 422 de FastAPI con lista de errores se resume en español con los campos', () => {
    const payload = {
      detail: [
        { type: 'string_too_long', loc: ['body', 'criteria', 0, 'left'], msg: 'String should have at most 500 characters' },
        { type: 'string_too_long', loc: ['body', 'criteria', 1, 'left'], msg: 'String should have at most 500 characters' },
        { type: 'missing', loc: ['body', 'operator'], msg: 'Field required' },
      ],
    };
    const message = researchErrorDetail(payload, FALLBACK);
    assert.equal(typeof message, 'string');
    assert.doesNotMatch(message, /\[object Object\]/);
    assert.equal(message, 'Datos no válidos en: left, operator. Revisa esos campos y vuelve a intentarlo.');
  });

  it('una lista sin loc utilizable da un aviso genérico en español, nunca [object Object]', () => {
    const message = researchErrorDetail({ detail: [{ msg: 'x' }, 'raro', null] }, FALLBACK);
    assert.equal(message, 'El motor de análisis rechazó los datos enviados. Revisa el formulario y vuelve a intentarlo.');
  });

  it('detail de texto se conserva tal cual', () => {
    assert.equal(researchErrorDetail({ detail: 'Sintaxis de fórmula no válida' }, FALLBACK), 'Sintaxis de fórmula no válida');
  });

  it('detail objeto con message anidado usa ese texto', () => {
    assert.equal(researchErrorDetail({ detail: { message: 'Filtro no encontrado' } }, FALLBACK), 'Filtro no encontrado');
  });

  it('sin detail usa message y, si no, el status HTTP', () => {
    assert.equal(researchErrorDetail({ message: 'Motor ocupado' }, FALLBACK), 'Motor ocupado');
    assert.equal(researchErrorDetail({ detail: { code: 1 } }, FALLBACK), FALLBACK);
    assert.equal(researchErrorDetail({ detail: '   ' }, FALLBACK), FALLBACK);
    assert.equal(researchErrorDetail(null, FALLBACK), FALLBACK);
    assert.equal(researchErrorDetail(['a'], FALLBACK), FALLBACK);
  });
});

describe('researchRequest con un 422 de validación del motor', () => {
  const originalFetch = globalThis.fetch;
  const originalBackend = process.env.FMP_BACKEND_URL;
  afterEach(() => {
    globalThis.fetch = originalFetch;
    if (originalBackend === undefined) delete process.env.FMP_BACKEND_URL;
    else process.env.FMP_BACKEND_URL = originalBackend;
  });

  it('lanza un error con mensaje legible en español, no «[object Object]»', async () => {
    process.env.FMP_BACKEND_URL = 'http://127.0.0.1:8001';
    globalThis.fetch = (async () => new Response(
      JSON.stringify({ detail: [{ type: 'string_too_long', loc: ['body', 'criteria', 0, 'left'], msg: 'String should have at most 500 characters' }] }),
      { status: 422, headers: { 'content-type': 'application/json' } },
    )) as typeof fetch;
    await assert.rejects(
      researchRequest('/api/screeners/run', { method: 'POST', body: '{}' }),
      (error: unknown) => {
        assert.ok(error instanceof Error);
        assert.equal(typeof error.message, 'string');
        assert.doesNotMatch(error.message, /\[object Object\]/);
        assert.match(error.message, /Datos no válidos en: left/);
        return true;
      },
    );
  });
});
