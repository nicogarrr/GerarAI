// Guard: la tarjeta de concentración del S&P 500 nunca pinta el `detail`
// crudo del backend (puede contener rutas /data/... o nombres de env vars);
// solo el texto mapeado para la persona usuaria.
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const SRC = readFileSync('components/market/MarketRegime.tsx', 'utf8');

test('existe el mapeo de motivos y se usa en vez del detail crudo', () => {
  assert.match(SRC, /MOTIVO_CONCENTRACION_SIN_DATOS/);
  assert.match(SRC, /motivoConcentracionSinDatos\(top\)/);
});

test('el detail del backend ya no se renderiza directamente', () => {
  assert.doesNotMatch(SRC, /top\.detail \?\? top\.reason/);
  assert.doesNotMatch(SRC, /\{top\.detail\}/);
});
