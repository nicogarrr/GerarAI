import { describe, expect, it } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';

import { scanContract } from '../../../scripts/contract-drift.mjs';

/**
 * Contrato frontend <-> data-engine: toda llamada tipada del frontend debe
 * cuadrar con el OpenAPI checked-in (paths, metodos, campos, nulabilidad,
 * enums, query params y cuerpos). El allowlist solo recoge falsos positivos
 * documentados y derivas con dueño asignado; cualquier deriva nueva rompe
 * este test. Regenera el esquema con `npm run generate:openapi`.
 */
describe('contrato OpenAPI frontend-backend', () => {
  it('sin deriva fuera del allowlist documentado', () => {
    // Ejecutar el CLI real fuera del proceso instrumentado por V8 evita
    // instrumentar tambien el compilador TypeScript y su grafo de tipos.
    // No se omite el scan ni se cambia su alcance: el CLI aplica el mismo
    // allowlist y sale con error ante cualquier deriva nueva.
    const result = JSON.parse(execFileSync(process.execPath, [
      resolve('scripts/contract-drift.mjs'),
      '--json',
    ], { encoding: 'utf8', timeout: 30_000 }));
    // El escaner debe seguir viendo el codigo: si deja de encontrar llamadas,
    // el test pasaria en falso.
    expect(result.summary.calls).toBeGreaterThan(250);
    expect(result.summary.open).toBe(0);
    expect(result.open).toEqual([]);
  }, 30_000);
});


it('flags static missing endpoints but records unresolved dynamic patterns separately', () => {
  const root = mkdtempSync(join(tmpdir(), 'contract-missing-'));
  try {
    mkdirSync(join(root, 'lib'));
    const spec = join(root, 'openapi.json');
    writeFileSync(spec, JSON.stringify({ paths: {} }));
    writeFileSync(join(root, 'lib', 'fixture.ts'), `
      declare function researchRequest(path: string): void;
      researchRequest('/api/this-endpoint-does-not-exist');
      declare const suffix: string;
      researchRequest(\`/api/dynamic/\${suffix}\`);
    `);
    const { findings, stats } = scanContract({ root, openapiPath: spec });
    expect(findings).toContainEqual(expect.objectContaining({ kind: 'ENDPOINT_NOT_IN_SPEC', endpoint: 'GET /api/this-endpoint-does-not-exist' }));
    expect(findings).toHaveLength(1);
    expect(stats.unmatched).toContainEqual(expect.objectContaining({ reason: 'dynamic-unresolved' }));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}, 30_000);

// El modo CLI usado arriba debe fallar cerrado, no devolver exito con derivas.
it('CLI exits nonzero and reports drift for an incompatible OpenAPI', () => {
  const root = mkdtempSync(join(tmpdir(), 'contract-cli-'));
  try {
    const spec = join(root, 'openapi.json');
    writeFileSync(spec, JSON.stringify({ paths: {} }));
    const result = spawnSync(process.execPath, [
      resolve('scripts/contract-drift.mjs'), '--json', '--openapi', spec,
    ], { encoding: 'utf8', timeout: 30_000 });
    expect(result.error).toBeUndefined();
    expect(result.status).toBe(1);
    const report = JSON.parse(result.stdout);
    expect(report.summary.calls).toBeGreaterThan(250);
    expect(report.summary.open).toBeGreaterThan(0);
    expect(report.open).toContainEqual(expect.objectContaining({ kind: 'ENDPOINT_NOT_IN_SPEC' }));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}, 30_000);
