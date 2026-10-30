import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { financialDefinition } from '@/lib/research/financial-display';

// Las definiciones del terminal financiero (pestaña de la ficha) llegan tal
// cual de financial_terminal_service.METRIC_DEFINITIONS_TEXT. Se leen del
// fuente Python para que una definición nueva o reescrita allí no se muestre
// en inglés sin que falle esto (la de owner_earnings salía casi entera en
// inglés tras reescribirse con la convención de signos).
function backendDefinitions(): Record<string, string> {
  const source = readFileSync(path.join(process.cwd(), 'data-engine/app/services/financial_terminal_service.py'), 'utf8');
  const block = /METRIC_DEFINITIONS_TEXT = \{([\s\S]*?)\n\}/.exec(source)?.[1] ?? '';
  return Object.fromEntries([...block.matchAll(/"([a-z_]+)":\s*"([^"]*)"/g)].map((m) => [m[1], m[2]]));
}

const ENGLISH = /\b(?:the|of|and|when|not|less|divided|by|over|with|net income|cash flow|working capital|reported|estimated|negative|shares|operating|profit|expense|earnings|letter|change in)\b/i;

describe('Terminal financiero · definiciones en español', () => {
  const definitions = backendDefinitions();

  it('lee todas las definiciones del backend', () => {
    expect(Object.keys(definitions)).toEqual(expect.arrayContaining(['revenue', 'free_cash_flow', 'owner_earnings']));
  });

  it.each(Object.entries(definitions))('%s se muestra en español', (_metric, text) => {
    const shown = financialDefinition(text);
    expect(shown).not.toBe(text);
    expect(shown).not.toMatch(ENGLISH);
  });

  it('owner earnings conserva fórmula y convención de signos', () => {
    const shown = financialDefinition(definitions.owner_earnings);
    expect(shown).toContain('carta de Berkshire Hathaway de 1986');
    expect(shown).toContain('negativa cuando el circulante absorbe caja');
    expect(shown).toContain('mínimo(|capex|, D&A)');
  });
});
