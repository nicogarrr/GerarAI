/**
 * Guard móvil (390px): el botón "Abrir el entorno completo de este nodo"
 * del panel Detalle del grafo envuelve el texto (whitespace-normal) en vez
 * de desbordar el ancho del panel, y su icono no se encoge.
 * Ejecutar: node --experimental-strip-types --test scripts/kg-detail-scopelink-wrap-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync('components/knowledge-graph/KnowledgeGraphCanvas.tsx', 'utf8');

describe('Grafo: el enlace de ambito del detalle envuelve el texto', () => {
  const bloque = src.slice(src.indexOf('detail.scopeLink') - 600, src.indexOf('detail.scopeLink'));

  it('el botón permite envolver y crecer en alto', () => {
    assert.match(bloque, /whitespace-normal/);
    assert.match(bloque, /h-auto/);
    assert.match(bloque, /py-2/);
    assert.match(bloque, /min-h-11/);
  });
  it('el icono no se encoge al envolver', () => {
    assert.match(bloque, /ExternalLink[^>]*shrink-0/);
  });
});
