/**
 * Guard F137 (/portfolio?tab=): la pestaña activa vive en la URL. Antes
 * el estado nacía fijo en 'resumen' y el parámetro se ignoraba tras la
 * hidratación. La guarda exige: lectura del param, validación contra la
 * lista de pestañas reales (ni una de mas ni de menos), escritura a la
 * URL al cambiar, y resumen como caída segura.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/portfolio-tab-param-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync('components/portfolio/PortfolioTabs.tsx', 'utf8');

const contentValues = [...source.matchAll(/TabsContent value="(\w+)"/g)].map((m) => m[1]);
assert.ok(contentValues.length > 0, 'no se encontraron TabsContent');

describe('portfolio tab param guard (F137)', () => {
  it('lee ?tab= de la URL', () => {
    assert.match(source, /useSearchParams/, 'debe leer searchParams');
    assert.match(source, /searchParams\.get\('tab'\)/, 'debe leer el parametro tab');
  });

  it('valida contra exactamente las pestañas que existen', () => {
    const listMatch = source.match(/VALID_TABS = \[([^\]]+)\]/);
    assert.ok(listMatch, 'debe existir VALID_TABS');
    const declared = [...listMatch[1].matchAll(/'(\w+)'/g)].map((m) => m[1]).sort();
    assert.deepEqual(declared, [...contentValues].sort(), 'VALID_TABS y TabsContent deben coincidir');
  });

  it('escribe la pestaña a la URL al cambiar y cae a resumen', () => {
    // replaceState nativo: la escritura es inmediata; router.replace esperaba
    // a la navegación RSC y dejaba la pestaña anterior en la URL ~1-2 s.
    assert.match(source, /window\.history\.replaceState\(null, '', `\$\{pathname\}\?\$\{params\.toString\(\)\}`\)/, 'debe escribir ?tab= al cambiar con replaceState (sincronía inmediata)');
    assert.match(source, /new URLSearchParams\(searchParams\.toString\(\)\)/, 'debe preservar los query params no-tab');
    assert.match(source, /'resumen'/, 'resumen es la caida segura');
    assert.equal(source.includes("useState('resumen')"), false, 'el estado ya no nace fijo ignorando la URL');
  });

  it('atrás/adelante sigue sincronizando el estado desde la URL', () => {
    assert.match(source, /useEffect\(\(\) => \{[\s\S]*?\}, \[tabParam\]\)/, 'el efecto de sincronización depende de tabParam');
  });
});
