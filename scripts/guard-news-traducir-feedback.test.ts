// Guard: el botón «Traducir» del resumen de noticias nunca hace no-op
// silencioso — si el motor no devuelve traducción se muestra el motivo
// (campo `reason` de la API, medido en prod 19-oct-2026: el fallo era
// invisible y el botón volvía a «Traducir» sin explicación).
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const SRC = readFileSync('components/research/NewsSummary.tsx', 'utf8');

test('estado de fallo declarado y visible con role=status', () => {
  assert.match(SRC, /const \[failure, setFailure\] = useState<string \| null>\(null\)/);
  assert.match(SRC, /role="status"/);
  assert.match(SRC, /t\('research\.translate\.genericFailure'\)/);
  assert.match(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).translate.genericFailure, /^Traducción no disponible ahora mismo/);
});

test('el motivo del motor se mapea a texto en español (con genérico de reserva)', () => {
  assert.match(SRC, /const REASON_KEYS = \{/);
  const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).translate;
  assert.equal(es.reason.badOutput, 'El traductor automático no dio un resultado fiable para este texto.');
  assert.equal(es.reason.providerRateLimited, 'Los traductores gratuitos están saturados ahora mismo. Inténtalo en unos minutos.');
  assert.equal(es.reason.providerTimeout, 'El traductor no respondió a tiempo. Inténtalo de nuevo en unos minutos.');
  assert.equal(Object.keys(es.reason).length, 9);
  assert.match(SRC, /provider_rate_limited/);
  assert.match(SRC, /provider_timeout/);
  assert.match(SRC, /bad_output/);
  assert.match(SRC, /Object\.hasOwn\(REASON_KEYS, failure\) \? t\(REASON_KEYS\[failure as keyof typeof REASON_KEYS\]\) : t\('research\.translate\.genericFailure'\)/);
});

test('cualquier respuesta sin traducción activa el feedback (nunca no-op)', () => {
  assert.match(SRC, /setFailure\(typeof data\?\.reason === 'string' \? data\.reason : 'unknown'\)/);
  assert.match(SRC, /\.catch\(\(\) => setFailure\('unknown'\)\)/);
});

test('el reintento limpia el feedback anterior', () => {
  assert.match(SRC, /setBusy\(true\);\s*setFailure\(null\);/);
});
