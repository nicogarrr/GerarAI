import { describe, expect, it } from 'vitest';

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
  });
});
