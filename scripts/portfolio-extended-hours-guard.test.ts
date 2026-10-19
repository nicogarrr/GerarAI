import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'components/portfolio/PortfolioHoldings.tsx'), 'utf8');

test('la cartera muestra la línea pre/post-mercado en tarjeta y tabla, con la divisa del listado', () => {
    assert.match(source, /import ExtendedHoursLine from '@\/components\/common\/ExtendedHoursLine'/);
    const renders = source.match(/<ExtendedHoursLine symbol=\{holding\.symbol\} currency=\{holding\.nativeCurrency\} \/>/g);
    assert.equal(renders?.length, 2, 'una línea en la tarjeta móvil y otra en la tabla');
});
