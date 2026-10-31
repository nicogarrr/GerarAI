/**
 * Guard paraguas: en las piezas con estados degradados declarados no puede
 * volver colarse un «pendiente» que prometa un trabajo futuro, ni un «no
 * disponible» sin decir qué falta.
 *
 * Cubre los seis puntos de la revisión que dejaron copy intermedio:
 * ProPicks (ficha, walk-forward, rebalanceo, caja del embudo), Impuestos
 * (casillas + fichero 720), Insider (lectura durable) y el asistente de
 * research (respuesta vacía).
 *
 * Lo que SÍ se admite, y por eso la lista es explícita y no un `pendiente`
 * genérico:
 *  - `dt.status === 'pendiente_tme'` es una CLAVE del backend, no copy visible.
 *  - «Reintenta más tarde» es acción sobre un fallo transitorio de red, no un
 *    estado a medio construir.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/no-pending-state-copy-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const SCOPE: Record<string, string> = {
  'components/proPicks/StrategyFactsheet.tsx': 'components/proPicks/StrategyFactsheet.tsx',
  'components/proPicks/WalkForwardResults.tsx': 'components/proPicks/WalkForwardResults.tsx',
  'components/proPicks/MonthlyRebalanceView.tsx': 'components/proPicks/MonthlyRebalanceView.tsx',
  'components/proPicks/EnhancedProPicksContent.tsx': 'components/proPicks/EnhancedProPicksContent.tsx',
  'components/proPicks/category-display.ts': 'components/proPicks/category-display.ts',
  'components/taxes/FilingSections.tsx': 'components/taxes/FilingSections.tsx',
  'components/insider/InsiderSignalsView.tsx': 'components/insider/InsiderSignalsView.tsx',
  'lib/insider-status-copy.ts': 'lib/insider-status-copy.ts',
  'components/brain/BrainGuideAnswer.tsx': 'components/brain/BrainGuideAnswer.tsx',
};

/** Promesas de trabajo futuro o estados sin cerrar, por fichero (case-insensitive). */
const BANNED = [
  /pendiente de validación/,
  /aún no tiene selección/,
  /aún no hay snapshot/,
  /aún sin snapshot/,
  /en cuanto estén disponibles/,
  /se publicará cuando/,
  /se habilitará cuando/,
  /cuando existan fundamentales/,
  /próximamente/,
  /en breve/,
  /estará disponible pronto/,
  /coming soon/i,
];

describe('copy sin estados intermedios en las piezas degradadas', () => {
  for (const [label, path] of Object.entries(SCOPE)) {
    it(`${label}: sin promesas de futuro ni copy de pendiente`, () => {
      const source = readFileSync(path, 'utf8');
      for (const banned of BANNED) {
        assert.ok(!banned.test(source), `${label}: prohibido ${banned}`);
      }
    });
  }

  it('la palabra «Pendiente» solo sobrevive como clave de backend o como acción del usuario', () => {
    const taxes = readFileSync('components/taxes/FilingSections.tsx', 'utf8');
    // Única aparición admitida: la clave del backend, en código.
    const occurrences = [...taxes.matchAll(/pendiente/gi)].map((match) => match.index ?? -1);
    assert.equal(occurrences.length, 1, 'una sola mención a «pendiente», la clave del backend');
    assert.match(taxes, /dt\.status === 'pendiente_tme'/);
  });

  it('las copias «no disponible» dicen qué haría falta', () => {
    const taxes = readFileSync('components/taxes/FilingSections.tsx', 'utf8');
    // El texto visible vive en el diccionario i18n (carril C); el componente
    // lo referencia por clave. El guard verifica ambos extremos.
    const esFiling = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8')).filing;
    assert.match(taxes, /taxes\.filing\.fallbackBoxes/);
    assert.match(esFiling.fallbackBoxes, /haría falta verificar ese mapeo/);
    const insider = readFileSync('lib/insider-status-copy.ts', 'utf8');
    assert.match(insider, /no una ausencia de Form 4/);
    const rebalance = readFileSync('components/proPicks/MonthlyRebalanceView.tsx', 'utf8');
    assert.match(rebalance, /solo conserva el último run del embudo/);
  });
});