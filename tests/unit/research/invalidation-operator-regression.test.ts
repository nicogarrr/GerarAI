import { expect, it } from 'vitest';
import { coerceInvalidationRules } from '@/lib/research/thesis-invalidation-rules';

// REPRO (rojo): `operator in OPERATOR_TEXT` acepta claves heredadas de Object.prototype.
it("operador 'constructor' no es válido", () => {
    expect(coerceInvalidationRules([{ metric: 'precio', operator: 'constructor', threshold: 1 }])).toEqual([]);
});
