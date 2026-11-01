/**
 * Guardas de la capa de UI: separadores es-ES, tabs móviles y etiquetas visibles.
 * Ejecución: node --experimental-strip-types --test scripts/ui-format-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { formatCompact, formatMarketCapUsd, formatMoney, formatNumber, formatPercent } from '../lib/format.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const source = (relativePath: string): string => readFileSync(join(root, relativePath), 'utf8');

describe('formato numérico es-ES', () => {
  it('formatCompact usa escala consistente M / mil M (B18)', () => {
    assert.equal(formatCompact(9447000), '9,45 M');
    assert.equal(formatCompact(9447000000), '9,45 mil M');
    assert.equal(formatCompact(416160000000), '416,16 mil M');
    assert.equal(formatCompact(1200000), '1,2 M');
    assert.equal(formatCompact(-2500000000), '-2,5 mil M');
    // 31-oct-2026: escala de billones (B) a partir de 1e12 — en prod la
    // capitalización de GOOGL salía «3.414 mil M US$», inlegible. Por debajo
    // de 1e12 la escala M / mil M se conserva exacta.
    assert.equal(formatCompact(4869930000000), '4,87 B');
    assert.equal(formatCompact(999999999999), '1 B');
    assert.equal(formatCompact(944700000000), '944,7 mil M');
  });

  it('formatMarketCapUsd: dólares en es-ES con la escala fija, sin cambiar el importe', () => {
    assert.equal(formatMarketCapUsd(4869930000000), '4,87 B\u00a0US$');
    assert.equal(formatMarketCapUsd(404010000000), '404,01 mil M\u00a0US$');
    assert.equal(formatMarketCapUsd(9447000000), '9,45 mil M\u00a0US$');
    assert.equal(formatMarketCapUsd(9447000), '9,45 M\u00a0US$');
    assert.equal(formatMarketCapUsd(4870000000), '4,87 mil M\u00a0US$');
    assert.equal(formatMarketCapUsd(1250), '1,25\u00a0mil\u00a0US$');
    assert.equal(formatMarketCapUsd(0), '0\u00a0US$');
    assert.equal(formatMarketCapUsd(-4870000000), '-4,87 mil M\u00a0US$');
    assert.equal(formatMarketCapUsd(Infinity), 'N/D');
    assert.equal(formatMarketCapUsd(null), 'N/D');
    assert.equal(formatMarketCapUsd('abc'), 'N/D');
  });

  it('la watchlist formatea el cap con su divisa real y no el sufijo US$', () => {
    const page = source('app/(root)/watchlist/page.tsx');
    assert.ok(page.includes('formatMarketCap(stock.marketCap, stock.currency)'));
    assert.ok(!page.includes('formatMarketCapUsd(stock.marketCap)'),
      'cap ya multi-divisa (respaldo backend no-US): el $ fijo inventaría la divisa');
    assert.ok(!page.includes('} US$`'), 'sin el sufijo US$ pegado al valor');
  });

  it('usa coma decimal en números, porcentajes e importes', () => {
    assert.equal(formatNumber(-0.8), '-0,8');
    assert.equal(formatPercent(-0.008, { digits: 2 }), '-0,80\u00a0%');
    assert.equal(formatMoney(1234.5), '1.234,50\u00a0US$');
    assert.equal(formatMoney(3127.58, 'EUR'), '3.127,58\u00a0€');
    assert.equal(formatMoney(1477.2, 'EUR'), '1.477,20\u00a0€');
  });
});

describe('guardas de UI', () => {
  it('la lista de ProPicks envuelve en móvil en vez de cortar pestañas', () => {
    // Tester 4 (2026-10-19): el scroll horizontal sin affordance cortaba
    // «Estrategia y rebalanc…»; las pestañas envuelven a dos filas.
    const tabs = source('components/proPicks/ProPicksTabs.tsx');
    for (const token of ['flex h-auto w-full min-w-0 max-w-full', 'flex-wrap', 'justify-start', 'pb-2', 'sm:inline-flex']) {
      assert.ok(tabs.includes(token), `ProPicksTabs debe contener ${token}`);
    }
    assert.ok(!tabs.includes('snap-x') && !tabs.includes('overflow-x-auto'), 'sin scroll horizontal oculto');
    const triggers = tabs.slice(tabs.indexOf('<TabsList'), tabs.indexOf('</TabsList>'));
    // «Estrategias» y «Rebalanceo» son la misma estrategia con dos lecturas
    // (el mismo currentStrategy): viven en una sola pestaña. La pestaña
    // «Joyas», «Deep value» y «Radar global» conviven con las cuatro originales.
    const triggerBlocks = [...triggers.matchAll(/<TabsTrigger[\s\S]*?>/g)].map((match) => match[0]);
    assert.equal(triggerBlocks.length, 8, 'ProPicks tiene picks, joyas, deepvalue, estrategia, backtest, paper trading, radar y oportunidades');
    for (const value of ['picks', 'joyas', 'deepvalue', 'estrategia', 'backtest', 'paper', 'radar', 'oportunidades']) {
      assert.ok(triggerBlocks.some((block) => block.includes(`value="${value}"`)), `falta trigger ${value}`);
    }
    // El contrato original, por trigger y no con un número suelto: cada uno
    // conserva su ANCHO NATURAL y nunca parte su etiqueta, para que a 390px
    // sea el contenedor, no cada tab, quien desborda horizontalmente. Una
    // pestaña nueva no puede colarse sin estas dos clases.
    for (const block of triggerBlocks) {
      assert.ok(block.includes('min-w-fit'), 'cada trigger debe conservar su ancho natural');
      assert.ok(block.includes('whitespace-nowrap'), 'cada trigger no debe partir su etiqueta');
    }
    assert.ok(!triggers.includes('w-max') && !triggers.includes('min-w-full'), 'la lista no debe crecer hasta el ancho del contenido');
  });

  it('ninguna pestaña queda huérfana: cada trigger tiene su TabsContent', () => {
    // El merge de Estrategias+Rebalanceo no puede dejar un trigger sin panel
    // (pestaña que al pulsarla no pintaría nada) ni un panel sin trigger.
    const tabs = source('components/proPicks/ProPicksTabs.tsx');
    const triggerValues = [...tabs.matchAll(/<TabsTrigger value="([^"]+)"/g)].map((match) => match[1]);
    const contentValues = [...tabs.matchAll(/<TabsContent value="([^"]+)"/g)].map((match) => match[1]);
    assert.ok(triggerValues.length > 0, 'no se encontraron TabsTrigger');
    assert.deepEqual([...triggerValues].sort(), [...contentValues].sort(), 'trigger y panel deben parearse uno a uno');
  });

  it('los formateadores UI de los módulos asignados no usan toFixed', () => {
    for (const file of [
      'lib/actions/screener.actions.ts',
      'lib/utils/advancedStockScoring.ts',
    ]) {
      assert.equal(source(file).includes('.toFixed('), false, `${file} debe delegar en lib/format.ts`);
    }
  });

  it('los valores Unknown visibles se traducen sin cambiar enums de API', () => {
    for (const file of [
      'lib/actions/finnhub.actions.ts',
      'lib/actions/screener.actions.ts',
      'lib/utils/advancedStockScoring.ts',
    ]) {
      assert.equal(source(file).includes("'Unknown'"), false, `${file} debe mostrar Desconocido`);
    }
    // El fallback 'Desconocido' vive en advancedStockScoring.ts (lo cubre el bucle);
    // proPicks.actions.ts ya no lee perfiles: sirve el run persistido del embudo F1.
    const scoring = source('lib/utils/advancedStockScoring.ts');
    assert.ok(scoring.includes("profile.finnhubIndustry ?? profile.industry"));
    assert.ok(scoring.includes("sectorRaw.length > 0 ? sectorRaw : 'Desconocido'"));
  });

  it('mantiene las etiquetas de estado en español sin cambiar enums de API', () => {
    // La credibilidad de la directiva es una sección de Seguimiento desde el 29-oct-2026.
    const credibility = source('components/research/sections/ManagementCredibilitySection.tsx');
    assert.ok(credibility.includes("partial: 'research.managementSection.statusPartial'"));
    assert.equal(JSON.parse(source('lib/i18n/messages/es/research.json')).managementSection.statusPartial, 'Parcial');
  });

  it('traduce el typo del monitor insider y no lo replica en la UI', () => {
    const insider = source('app/(root)/insider/page.tsx');
    assert.ok(!insider.includes('Metodología · Monitor cada 15 min'), 'el bloque de telemetría ya no se muestra');
    assert.equal(insider.includes('monitor automatico'), false);
  });
});
