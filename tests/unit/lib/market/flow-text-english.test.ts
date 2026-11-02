import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { flowText, localizeFlow } from '@/lib/market/flow-text';
import type { MoneyFlow } from '@/lib/market/flows';

const SPANISH = /[áéíóúñ¿¡]|\b(?:de|del|los|las|por|una|para|sin|con|su|sus|es|y|que|en|se|al)\b/i;

/** Literales de una línea del backend que llegan al usuario (sin docstrings, comentarios ni mensajes internos). */
function backendLiterals(path: string): string[] {
  const src = readFileSync(path, 'utf8')
    .replace(/"""[\s\S]*?"""/g, '')
    .replace(/#.*$/gm, '')
    .replace(/raise \w+\([^)]*\)/g, '')
    .replace(/"\s*\n\s*"/g, '');
  return [...src.matchAll(/(?<![\w])"([^"\n]{3,})"/g)].map((m) => m[1]).filter((s) => SPANISH.test(s) || /^[A-ZÁÉÍÓÚ][a-záéíóúñ]+(?: [a-záéíóúñ]+)*$/.test(s));
}

const IGNORED = new Set(['Department of Defense', 'million dollars', 'ALL', 'US Total']);

describe('Flujos de dinero de Temas en inglés: textos del backend sin castellano', () => {
  it('cada texto fijo de money_flows.py y energy_flows.py tiene versión en inglés', () => {
    const literals = [
      ...backendLiterals('data-engine/app/services/money_flows.py'),
      ...backendLiterals('data-engine/app/services/energy_flows.py'),
    ].filter((s) => !IGNORED.has(s) && (s.includes(' ') || /^[A-ZÁÉÍÓÚ]/.test(s)));
    expect(literals.length).toBeGreaterThan(80);
    const missing = literals.filter((s) => SPANISH.test(s) && flowText(s, 'en') === s);
    expect(missing).toEqual([]);
    for (const s of literals) {
      expect(flowText(s, 'es')).toBe(s);
      if (flowText(s, 'en') !== s) expect(flowText(s, 'en'), s).not.toMatch(SPANISH);
    }
  });

  it('los textos con cifras conservan los valores', () => {
    expect(flowText('Principales categorías: cubren el 62 % de lo obligado', 'en')).toBe('Top categories: they cover 62% of the obligated amount');
    expect(flowText('Principales recipientes: cubren el 31 % de lo obligado', 'en')).toBe('Top recipients: they cover 31% of the obligated amount');
    expect(flowText('Obligaciones FY2025 federal (oct 2024–sep 2025)', 'en')).toBe('Obligations FY2025 federal (Oct 2024–Sep 2025)');
    expect(flowText('USAspending no disponible ahora mismo (HTTPStatusError); sin cifras en lugar de inventarlas', 'en'))
      .toBe('USAspending unavailable right now (HTTPStatusError); no figures rather than made-up ones');
    expect(flowText('5 de 7 gastadores incluidos (solo USD reportado); los periodos no coinciden necesariamente entre empresas', 'en'))
      .toBe("5 of 7 spenders included (reported USD only); periods don't necessarily match across companies");
    expect(flowText('5 de 5 sectores incluidos · EE. UU. 2024; ALL es control, no se suma otra vez', 'en')).toBe('5 of 5 sectors included · US 2024; ALL is a control total, not added again');
    expect(flowText('USAspending.gov · categoría PSC 1510 · FY2025 federal (oct 2024–sep 2025)', 'en')).toBe('USAspending.gov · PSC category 1510 · FY2025 federal (Oct 2024–Sep 2025)');
    expect(flowText('EIA · ventas eléctricas EE. UU. · 2024', 'en')).toBe('EIA · US electricity sales · 2024');
    expect(flowText('Texto desconocido', 'en')).toBe('Texto desconocido');
  });

  it('las plantillas con cifras del backend siguen siendo las que se traducen', () => {
    const money = readFileSync('data-engine/app/services/money_flows.py', 'utf8').replace(/"\s*\n\s*"/g, '');
    const energy = readFileSync('data-engine/app/services/energy_flows.py', 'utf8');
    for (const s of ['Principales categorías: cubren el {', 'Principales recipientes: cubren el {', ' % de lo obligado', 'f"Obligaciones {fy_label}"',
      '({type(exc).__name__}); sin cifras en lugar de inventarlas', ' gastadores incluidos (solo USD reportado); los periodos no coinciden necesariamente entre empresas',
      'categoría PSC {code} · {fy_label}', 'f"FY{fy_end_year} federal (oct {start.year}–sep {end.year})"']) expect(money).toContain(s);
    for (const s of ['5 de 5 sectores incluidos · EE. UU. {year}; ALL es control, no se suma otra vez', 'EIA · ventas eléctricas EE. UU. · {year}']) expect(energy).toContain(s);
  });

  it('localizeFlow traduce el flujo entero en inglés y no toca nada en castellano', () => {
    const flow: MoneyFlow = {
      id: 'defensa', name: 'Defensa de EE. UU.', tagline: 'Del presupuesto federal a los contratistas', generated_at: '2026-11-02T00:00:00Z',
      period_label: 'FY2025 federal (oct 2024–sep 2025)',
      spenders: [{ key: 'us-dod', label: 'Departamento de Defensa de EE. UU.', ticker: null, amount: 1, unit: 'USD', period_label: null,
        source: { kind: 'reportado', label: 'USAspending.gov · FY2025 federal (oct 2024–sep 2025)', url: 'https://x', note: 'Obligaciones de contratos y ayudas; no incluye personal ni operaciones internas' },
        reason: 'Mayor agencia federal por obligaciones de contratos y ayudas.', note: null, extra_amount: null, extra_label: null, extra_source: null }],
      spenders_total: null,
      destinations: [{ label: 'Buques de guerra', amount: 1, unit: 'USD', source: { kind: 'reportado', label: 'USAspending.gov · categoría PSC 1905 · FY2025 federal (oct 2024–sep 2025)', url: null, note: null } }],
      suppliers: [{ ticker: 'LMT', name: 'LOCKHEED MARTIN', amount: 1, unit: 'USD', reason: 'Mayor contratista de defensa de EE. UU. por obligaciones.', note: 'Obligaciones FY2025 federal (oct 2024–sep 2025)', source: null }],
      method: 'Obligaciones de contratos y ayudas de USAspending.gov (API oficial), último año fiscal completo', limitation: 'x',
      notes: [], destinations_note: 'Principales categorías: cubren el 40 % de lo obligado', suppliers_note: 'Principales recipientes: cubren el 30 % de lo obligado',
    };
    expect(localizeFlow(flow, 'es')).toBe(flow);
    const en = localizeFlow(flow, 'en');
    const texts = [en.name, en.tagline, en.method, en.destinations_note, en.suppliers_note, en.spenders[0].label, en.spenders[0].reason,
      en.spenders[0].source?.note, en.destinations[0].label, en.destinations[0].source.label, en.suppliers[0].reason, en.suppliers[0].note];
    for (const s of texts) expect(s).not.toMatch(SPANISH);
    expect(en.suppliers[0].name).toBe('LOCKHEED MARTIN');
    expect(en.spenders[0].source?.url).toBe('https://x');
  });

  it('el detalle del tema pinta el flujo traducido', () => {
    const src = readFileSync('app/(root)/temas/_components/ThemeFlow.tsx', 'utf8');
    expect(src).toContain('localizeFlow(');
  });
});
