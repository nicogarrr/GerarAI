// Guard: la tarjeta de concentración del S&P 500 nunca pinta el `detail`
// crudo del backend (puede contener rutas /data/... o nombres de env vars);
// solo el texto mapeado para la persona usuaria.
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const SRC = readFileSync('components/market/MarketRegime.tsx', 'utf8');

test('existe el mapeo de motivos y se usa en vez del detail crudo', () => {
  assert.match(SRC, /MOTIVO_CONCENTRACION_SIN_DATOS/);
  assert.match(SRC, /motivoConcentracionSinDatos\(top[,)]/);
});

test('el detail del backend ya no se renderiza directamente', () => {
  assert.doesNotMatch(SRC, /top\.detail \?\? top\.reason/);
  assert.doesNotMatch(SRC, /\{top\.detail\}/);
});

// Cobertura completa: cada `reason` que el backend puede emitir para la
// tarjeta de concentración (constantes REASON_* del conector del factsheet y
// literales snake_case de sp500_top_ten_concentration) tiene texto honesto en
// el mapa; sin entrada, la tarjeta caía en un «no está disponible» falso.
const CONNECTOR = readFileSync('data-engine/app/services/connectors/sp500_factsheet.py', 'utf8');
const QUANT = readFileSync('data-engine/app/services/market_regime_quant.py', 'utf8');

test('cada reason del backend de concentración tiene texto mapeado', () => {
  const mapKeys = [...SRC.matchAll(/^ {2}([a-z0-9_]+): '/gm)].map((m) => m[1]);
  const backendReasons = new Set([
    ...[...CONNECTOR.matchAll(/REASON_\w+ = "([a-z0-9_]+)"/g)].map((m) => m[1]),
    ...[...QUANT.matchAll(/"reason": "([a-z0-9_]+)"/g)].map((m) => m[1]),
  ]);
  assert.ok(backendReasons.size >= 7, `reasons detectados insuficientes: ${[...backendReasons].join(', ')}`);
  for (const reason of backendReasons) {
    assert.ok(mapKeys.includes(reason), `reason sin mapear: ${reason}`);
  }
});
