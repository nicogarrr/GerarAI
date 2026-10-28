/**
 * F390: la UI permitía 21-50 años y el backend (work_products.py, le=20)
 * respondía 422. El límite de la UI debe coincidir con el del backend.
 * Ejecución: node --experimental-strip-types --test scripts/work-product-years-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = (p: string): string => readFileSync(join(root, p), 'utf8');

describe('años de los work products', () => {
    it('la UI usa el mismo máximo que el backend', () => {
        const backend = source('data-engine/app/api/routes/work_products.py');
        const maxYears = Number(/years: int = Field\([^)]*le=(\d+)/.exec(backend)?.[1]);
        assert.ok(Number.isFinite(maxYears));
        const ui = source('components/work-products/WorkProductDialog.tsx');
        assert.match(ui, new RegExp(`Math\\.min\\(${maxYears},`));
        assert.match(ui, new RegExp(`max=\\{${maxYears}\\}`));
    });
});
