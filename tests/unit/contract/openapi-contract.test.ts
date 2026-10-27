import { describe, expect, it } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { applyAllowlist, loadAllowlist, scanContract } from '../../../scripts/contract-drift.mjs';

/**
 * Contrato frontend <-> data-engine: toda llamada tipada del frontend debe
 * cuadrar con el OpenAPI checked-in (paths, metodos, campos, nulabilidad,
 * enums, query params y cuerpos). El allowlist solo recoge falsos positivos
 * documentados y derivas con dueño asignado; cualquier deriva nueva rompe
 * este test. Regenera el esquema con `npm run generate:openapi`.
 */
describe('contrato OpenAPI frontend-backend', () => {
  it('sin deriva fuera del allowlist documentado', () => {
    const { stats, findings } = scanContract({});
    // El escaner debe seguir viendo el codigo: si deja de encontrar llamadas,
    // el test pasaria en falso.
    expect(stats.calls).toBeGreaterThan(250);
    const open = applyAllowlist(findings, loadAllowlist());
    expect(open).toEqual([]);
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
