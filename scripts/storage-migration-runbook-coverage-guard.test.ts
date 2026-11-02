/**
 * Guard: los runbooks de la migración MinIO -> Garage
 * (docs/RUNBOOK_PILOTO_MINIO_GARAGE.md y docs/OBJECT_STORAGE_MIGRATION.md)
 * paran y rearrancan TODOS los servicios que heredan el ancla `x-app-env`
 * de `docker-compose.prod.yml` (llevan MINIO_*).
 *
 * La parada total es la garantía documentada de la ventana («no se afirma
 * que no escriban; un actor puede llegar al storage transitivamente»), pero
 * las listas se quedaron cortas en dos sitios: el rollback decía «la misma
 * lista del paso 2» con solo 8 de los 14 servicios, y el rearranque tras el
 * corte (`up -d`) no devolvía los seis workers de colas de datos en ningún
 * paso — backup.sh para y rearranca esos mismos 14 en cada backup
 * (scripts/backup.sh), es decir, forman parte del estado normal en prod.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/storage-migration-runbook-coverage-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const compose = readFileSync('docker-compose.prod.yml', 'utf8');
const runbook = readFileSync('docs/RUNBOOK_PILOTO_MINIO_GARAGE.md', 'utf8');
const estrategia = readFileSync('docs/OBJECT_STORAGE_MIGRATION.md', 'utf8');

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

// Bloques de comando compose (con continuaciones `\`): cada línea
// `docker compose -p cavaai -f docker-compose.prod.yml <verbo> ...` más las
// líneas siguientes mientras la anterior termine en `\`.
function composeBlocks(text: string, verb: 'stop' | 'up -d'): string[] {
  const lines = text.split('\n');
  const blocks: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].includes('docker compose -p cavaai -f docker-compose.prod.yml ' + verb)) continue;
    let block = lines[i];
    while (block.trimEnd().endsWith('\\') && i + 1 < lines.length) {
      i++;
      block += '\n' + lines[i];
    }
    blocks.push(block);
  }
  return blocks;
}

const producers = servicesWithAppEnv(compose);
assert.ok(producers.length >= 8, 'el parseo del compose no encontro los servicios esperados');

// Comparacion por tokens exactos: con substring, «worker» pasaria si solo
// quedara «worker-thesis», y «worker-yahoo» si quedara «worker-yahoo-news».
function lineCovers(line: string, service: string): boolean {
  return new Set(line.split(/[\s`]+/)).has(service);
}

describe('runbook MinIO -> Garage: cada parada y cada rearranque cubre todos los servicios con x-app-env', () => {
  const paradas = composeBlocks(runbook, 'stop');
  const rearranques = composeBlocks(runbook, 'up -d');
  it('el runbook tiene las dos paradas (ventana y rollback) y el rearranque', () => {
    assert.equal(paradas.length, 2, `paradas encontradas: ${paradas.length}`);
    assert.equal(rearranques.length, 1, `rearranques encontrados: ${rearranques.length}`);
  });
  for (const [nombre, bloques] of [['parada', paradas], ['rearranque', rearranques]] as const) {
    for (const [indice, bloque] of bloques.entries()) {
      for (const svc of producers) {
        it(`${nombre} ${indice + 1} cubre ${svc}`, () => {
          assert.ok(lineCovers(bloque, svc), `${svc} no esta en ${nombre} ${indice + 1} del runbook`);
        });
      }
    }
  }
});

describe('OBJECT_STORAGE_MIGRATION fase 3: parada y rearranque cubren todos los servicios con x-app-env', () => {
  const paradas = composeBlocks(estrategia, 'stop');
  const rearranques = composeBlocks(estrategia, 'up -d');
  it('la fase 3 tiene una parada y un rearranque', () => {
    assert.equal(paradas.length, 1, `paradas encontradas: ${paradas.length}`);
    assert.equal(rearranques.length, 1, `rearranques encontrados: ${rearranques.length}`);
  });
  for (const [nombre, bloques] of [['parada', paradas], ['rearranque', rearranques]] as const) {
    for (const bloque of bloques) {
      for (const svc of producers) {
        it(`${nombre} cubre ${svc}`, () => {
          assert.ok(lineCovers(bloque, svc), `${svc} no esta en el ${nombre} de la fase 3`);
        });
      }
    }
  }
});

describe('la comparacion es por tokens (mutaciones)', () => {
  it('sin «worker» aunque queden otros worker-*, el guard falla', () => {
    const soloOtros = 'docker compose stop worker-thesis worker-yahoo scheduler';
    assert.equal(lineCovers(soloOtros, 'worker'), false);
    assert.equal(lineCovers(soloOtros, 'worker-thesis'), true);
  });

  it('«worker-yahoo-news» no cubre «worker-yahoo»', () => {
    const soloNews = 'docker compose stop backend worker-yahoo-news scheduler';
    assert.equal(lineCovers(soloNews, 'worker-yahoo'), false);
    assert.equal(lineCovers(soloNews, 'worker-yahoo-news'), true);
  });

  it('una parada con solo la lista antigua de 8 no pasa por parada completa', () => {
    const listaAntigua = composeBlocks(runbook, 'stop')
      .map((b) => b.replace(/ worker-official-closes[^\n\\]*/g, ''));
    assert.ok(listaAntigua.every((b) => !lineCovers(b, 'worker-official-closes')));
  });
});
