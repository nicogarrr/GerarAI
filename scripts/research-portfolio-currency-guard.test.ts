import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// F91: el contexto de cartera de /research no puede pintar los importes con
// una moneda inventada ('USD' fijo): usa la base_currency del backend o NA.

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

void test('los importes del contexto de cartera usan la moneda base del backend', () => {
  const page = source('app/(root)/research/page.tsx');
  assert.ok(!page.includes("formatMoney(value, 'USD'"), 'moneda fija USD prohibida');
  assert.ok(!page.includes('portfolio.total_value'), 'el índice no duplica las cifras de cartera');
});

void test('sin moneda base no se inventa símbolo: NA honesto', () => {
  const page = source('app/(root)/research/page.tsx');
  assert.ok(!page.includes('Contexto de cartera'), 'contexto retirado del índice');
  // El resumen de cartera del índice llega via getPortfolioSummary
  // (portfolio.actions): el dashboard ya no duplica /api/portfolio/summary.
  // Los tipos del front son alias del OpenAPI generado (response_model en el
  // backend): la declaracion vive en openapi.generated.ts.
  const generated = source('lib/research/openapi.generated.ts');
  assert.ok(/PortfolioForecastOut: \{[\s\S]*?base_currency: string \| null;/.test(generated), 'el tipo generado declara base_currency');
});
