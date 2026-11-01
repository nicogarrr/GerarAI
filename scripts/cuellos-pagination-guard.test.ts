/**
 * Canario de /cuellos: una página fuera de rango (?pagina=999 con total>0)
 * NUNCA puede anunciar "sin candidatos" (falso) ni ocultar la navegación.
 * Ejecución: node --experimental-strip-types --test scripts/cuellos-pagination-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
// Los textos viven en es/bottlenecks.json: solo se añade la sección de la página.
const page = readFileSync(join(here, '..', 'app', '(root)', 'cuellos', 'page.tsx'), 'utf8')
  + JSON.stringify(JSON.parse(readFileSync(join(here, '..', 'lib', 'i18n', 'messages', 'es', 'bottlenecks.json'), 'utf8')).page);

describe('/cuellos paginación honesta', () => {
  it('el estado vacío exige total === 0, no solo items vacíos', () => {
    assert.ok(
      page.includes('discoveries.items.length === 0 && discoveries.total === 0'),
      'el mensaje "Sin candidatos todavía" solo es cierto con total === 0',
    );
  });

  it('una página fuera de rango con total > 0 tiene su propio estado y salida', () => {
    assert.ok(page.includes('Página fuera de rango'), 'estado diferenciado para página inexistente');
    assert.ok(page.includes('Math.ceil(discoveries.total / PAGE_SIZE)'), 'totalPages derivado del total real');
    assert.ok(page.includes('Primera página'), 'enlace de vuelta a la primera página');
    assert.ok(page.includes('pageHref(totalPages)'), 'enlace a la última página real');
  });
});

it('las señales permiten comprobar las fuentes, no solo ver un recuento', () => {
  assert.ok(page.includes('Ver evidencias guardadas'));
  assert.ok(page.includes("item.status === 'verificada' && item.url"));
  assert.ok(page.includes('sin enlace verificable'));
});
