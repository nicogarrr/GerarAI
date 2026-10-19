/**
 * Guard de persistencia de la selección ProPicks al cambiar de pestaña.
 *
 * Reproducido en producción (2026-10-19, cuenta Instinct Audit): con la
 * pestaña «Selección IA» activa se aplica «Ordenar por: Crecimiento» y se
 * confirma «Selección consultada: 8 empresas»; se abre «Joyas» y se vuelve a
 * «Selección IA» y la selección/filtros vuelven al render inicial (Radix Tabs
 * desmonta el panel inactivo y EnhancedProPicksContent se siembra solo con
 * initialPicks del SSR). Con «Generar selección ahora» (sin run previo) el
 * run generado desaparecía por completo al volver a la pestaña.
 *
 * El panel de Selección IA va con forceMount: montado siempre, el estado del
 * componente (selección generada/actualizada, filtros) sobrevive al cambio de
 * pestaña. Una recarga completa re-renderiza en servidor con el último run
 * persistido, así que ambos caminos muestran la selección vigente.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/propicks-seleccion-persiste-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const tabs = readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8');

describe('ProPicks: la selección persiste al volver a la pestaña «Selección IA»', () => {
  it('el panel de Selección IA se monta con forceMount', () => {
    assert.match(
      tabs,
      /<TabsContent\s+value="picks"\s+forceMount/,
      'TabsContent value="picks" tiene que llevar forceMount para no perder la selección al cambiar de pestaña',
    );
  });

  it('solo el panel de Selección IA usa forceMount (el resto sigue perezoso)', () => {
    const matches = tabs.match(/<TabsContent[^>]*\sforceMount/g) ?? [];
    assert.equal(matches.length, 1, `esperaba 1 TabsContent con forceMount y hay ${matches.length}`);
  });

  it('el panel monta EnhancedProPicksContent con la semilla del SSR', () => {
    assert.match(tabs, /<EnhancedProPicksContent\s+initialPicks=\{initialPicks\}/);
  });

  it('forceMount lleva un hidden explícito: montado siempre, visible solo en su pestaña', () => {
    // @radix-ui/react-tabs 1.2.1 calcula `hidden: !present`; con forceMount
    // present es siempre true y la parrilla de picks quedaba VISIBLE en las
    // 5 pestañas (Tester 6, 2026-10-19). El `hidden` ligado a activeTab manda
    // porque contentProps se expande después del cálculo interno.
    assert.match(
      tabs,
      /<TabsContent\s+value="picks"\s+forceMount\s+hidden=\{activeTab !== 'picks'\}/,
      'forceMount sin hidden explícito deja la parrilla visible en todas las pestañas',
    );
  });
});
