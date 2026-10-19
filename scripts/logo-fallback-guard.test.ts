/**
 * Guard: los logos de empresa nunca pintan una caja blanca vacía ni un
 * marco blanco horneado (HIMS/UNH/UBER y BN/AMZN medidos el 2026-10-20).
 *
 * Contrato:
 * - analyzeLogoPixels detecta el placeholder invisible de FMP (HTTP 200 con
 *   PNG vacío) como blank -> CompanyLogo cae a las iniciales (NameAvatar).
 * - El margen blanco horneado se recorta a la caja de contenido (bbox).
 * - El contenedor se rellena con el color de la esquina del logo, no con un
 *   marco blanco; logo transparente -> fondo blanco legible.
 * - La vista lista pide CORS (crossOrigin) para poder medir píxeles y no
 *   lleva el padding p-1 que encogía todos los logos.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/logo-fallback-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extension .ts explicita la exige node --experimental-strip-types en runtime
const { analyzeLogoPixels } = await import('../lib/logo-analysis.ts');

const vista = readFileSync('components/calendar/CompanyLogo.tsx', 'utf8');

/** Imagen sintética: `paint(x, y)` devuelve [r,g,b,a] por píxel. */
function pixels(w: number, h: number, paint: (x: number, y: number) => [number, number, number, number]) {
  const data = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const [r, g, b, a] = paint(x, y);
      const i = (y * w + x) * 4;
      data[i] = r; data[i + 1] = g; data[i + 2] = b; data[i + 3] = a;
    }
  }
  return data;
}

const BLANCO: [number, number, number, number] = [255, 255, 255, 255];
const HUECO: [number, number, number, number] = [0, 0, 0, 0];
const TINTA: [number, number, number, number] = [20, 40, 90, 255];

describe('analyzeLogoPixels: placeholder y marco del proveedor', () => {
  it('placeholder de FMP: todo blanco o todo transparente es blank (HIMS/UNH/UBER)', () => {
    assert.equal(analyzeLogoPixels(8, 8, pixels(8, 8, () => BLANCO)).blank, true);
    assert.equal(analyzeLogoPixels(8, 8, pixels(8, 8, () => HUECO)).blank, true);
    // Niebla: <2% de contenido también es placeholder (niebla de compresión).
    const niebla = pixels(32, 32, (x, y) => (x === 3 && y === 3 ? TINTA : HUECO));
    assert.equal(analyzeLogoPixels(32, 32, niebla).blank, true);
  });

  it('logo que llena el lienzo: bbox completo y color de esquina', () => {
    const a = analyzeLogoPixels(10, 10, pixels(10, 10, () => TINTA));
    assert.equal(a.blank, false);
    assert.deepEqual(a.bbox, { x: 0, y: 0, w: 10, h: 10 });
    assert.equal(a.background, 'rgb(20, 40, 90)');
    assert.ok(a.contentRatio > 0.95);
  });

  it('margen horneado (BN/AMZN): recorta a la caja de contenido', () => {
    // Logo 4x4 centrado en lienzo blanco de 20x20 = 4% de contenido.
    const a = analyzeLogoPixels(20, 20, pixels(20, 20, (x, y) => (x >= 8 && x < 12 && y >= 8 && y < 12 ? TINTA : BLANCO)));
    assert.equal(a.blank, false);
    assert.equal(a.bbox.w <= 8 && a.bbox.h <= 8, true, `bbox ajustada: ${JSON.stringify(a.bbox)}`);
    assert.ok(a.bbox.x <= 8 && a.bbox.x + a.bbox.w >= 12, 'la caja cubre todo el contenido');
    assert.equal(a.background, 'rgb(255, 255, 255)');
  });

  it('logo transparente (AAPL): contenido detectado, fondo null para bg blanco', () => {
    const a = analyzeLogoPixels(10, 10, pixels(10, 10, (x, y) => (x >= 2 && x < 8 && y >= 2 && y < 8 ? TINTA : HUECO)));
    assert.equal(a.blank, false);
    assert.equal(a.background, null);
  });
});

describe('CompanyLogo: la caja blanca vacía no puede volver', () => {
  it('mide píxeles con CORS y cae a iniciales si el logo está en blanco', () => {
    assert.ok(vista.includes('analyzeLogoPixels'), 'el análisis de píxeles decide');
    assert.ok(vista.includes('crossOrigin="anonymous"'), 'sin CORS el canvas se contamina');
    assert.ok(vista.includes("setFailedFor(ticker)"), 'placeholder -> fallback');
    assert.match(vista, /<NameAvatar name=\{name \|\| ticker\}/, 'iniciales como red honesta');
  });

  it('el logo listo llena el contenedor sin marco ni padding', () => {
    assert.ok(vista.includes('analysis.bbox'), 'recorta el margen horneado');
    assert.ok(vista.includes('ready?.background'), 'rellena con el color del logo');
    const ramaLista = vista.split('ready\n?')[1] ?? '';
    assert.ok(!ramaLista.includes('p-1'), 'sin padding en la imagen lista');
    assert.ok(vista.includes("object-contain"), 'sin deformar ni recortar el logo');
  });
});
