/**
 * Guard: `scripts/backup.sh --stop-storage` para TODOS los servicios que
 * heredan el ancla `x-app-env` de `docker-compose.prod.yml` (lleva MINIO_*).
 *
 * Un worker con acceso a la config de storage que siga vivo durante el tar
 * de MinIO es la misma duda que el propio script documenta para
 * worker-knowledge: pararlo cuesta cero. La lista se quedo vieja cuando
 * llegaron official-closes/prices/externa/finnhub/yahoo/dca-manual; este
 * guard la ata al compose para que no vuelva a quedarse corta.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/backup-stop-storage-coverage-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const compose = readFileSync('docker-compose.prod.yml', 'utf8');
const backup = readFileSync('scripts/backup.sh', 'utf8');

// Servicios cuyo bloque environment fusiona el ancla con MINIO_*.
function servicesWithAppEnv(text: string): string[] {
  const names: string[] = [];
  let current: string | null = null;
  for (const line of text.split('\n')) {
    const m = /^  ([a-z0-9-]+):\s*$/.exec(line);
    if (m) current = m[1];
    if (current && line.includes('<<: [*app-env')) names.push(current);
  }
  return names;
}

function composeLine(script: string, verb: 'stop' | 'start'): string {
  const line = script
    .split('\n')
    .find((l) => l.includes('${COMPOSE} ' + verb));
  assert.ok(line, `scripts/backup.sh no tiene linea de ${verb}`);
  return line;
}

const producers = servicesWithAppEnv(compose);
assert.ok(producers.length >= 8, 'el parseo del compose no encontro los servicios esperados');

// Comparacion por tokens exactos: con substring, «worker» pasaria si solo
// quedara «worker-thesis», y «worker-yahoo» si quedara «worker-yahoo-news».
function lineCovers(line: string, service: string): boolean {
  return new Set(line.trim().split(/\s+/)).has(service);
}

describe('backup.sh --stop-storage cubre todos los servicios con x-app-env', () => {
  for (const svc of producers) {
    it(`para y rearranca ${svc}`, () => {
      assert.ok(lineCovers(composeLine(backup, 'stop'), svc), `${svc} no esta en la parada de --stop-storage`);
      assert.ok(lineCovers(composeLine(backup, 'start'), svc), `${svc} no esta en el rearranque tras el backup`);
    });
  }
});

describe('la comparacion es por tokens (mutaciones)', () => {
  const stop = composeLine(backup, 'stop');

  it('sin «worker» aunque queden otros worker-*, el guard falla', () => {
    const mutated = stop.replace(/ worker( |$)/, '$1');
    assert.ok(!stop.includes('worker-thesis') || !lineCovers(mutated, 'worker'));
    assert.equal(lineCovers(mutated, 'worker'), false);
  });

  it('«worker-yahoo-news» no cubre «worker-yahoo»', () => {
    const soloNews = '${COMPOSE} stop backend worker-yahoo-news scheduler';
    assert.equal(lineCovers(soloNews, 'worker-yahoo'), false);
    assert.equal(lineCovers(soloNews, 'worker-yahoo-news'), true);
  });

  it('el ultimo token de la linea tambien cuenta', () => {
    assert.equal(lineCovers('${COMPOSE} stop backend worker', 'worker'), true);
  });
});
