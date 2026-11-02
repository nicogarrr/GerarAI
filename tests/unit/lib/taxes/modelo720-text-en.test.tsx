import { readFileSync } from 'node:fs';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import { humanizeTaxText } from '@/lib/taxes/humanize-text';
import { taxText } from '@/lib/taxes/tax-text';
import data from '@/lib/taxes/tax-text-en.json';
import { Modelo720Section } from '@/components/taxes/FilingSections';

// El backend parte las frases en literales seguidos ("…" "…"): se juntan para
// buscar cada frase traducida tal cual está en el código.
const backend = ['tax_modelo720_service.py', 'tax_modelo720_file.py']
  .map((file) => readFileSync(`data-engine/app/services/${file}`, 'utf8'))
  .join('\n')
  .replace(/"\s*\n\s*f?"/g, '')
  .replace(/" \+ ", "\.join\([^)]*\) \+\s*"/g, '');
const SPANISH = /[áéíóúñ¿¡«»]|\b(?:de|del|los|las|por|una|para|sin|con|su|sus|es|y|que|en|se|al|fuera|saldo|cuenta|cartera|falta)\b/i;

describe('Modelo 720 en inglés: motivos, notas y avisos del motor fiscal', () => {
  it('cada frase traducida sigue existiendo en el backend (si cambia allí, este test avisa)', () => {
    const exact = Object.keys(data.exact);
    expect(exact.length).toBeGreaterThan(30);
    expect(exact.filter((es) => !backend.includes(es))).toEqual([]);
    const parts = (data.templates as [string, string][])
      .flatMap(([es]) => es.split(/\{\w+\}/))
      .filter((part) => part.trim().length > 3);
    expect(parts.filter((part) => !backend.includes(part))).toEqual([]);
  });

  it('las traducciones no llevan castellano y usan los mismos datos', () => {
    for (const [es, en] of Object.entries(data.exact)) {
      expect(en, es).not.toMatch(SPANISH);
      expect(taxText(es, 'en')).toBe(en);
    }
    for (const [es, en] of data.templates as [string, string][]) {
      expect(en, es).not.toMatch(SPANISH);
      expect([...en.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()).toEqual([...es.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort());
    }
  });

  it('textos reales del backend, con sus datos', () => {
    expect(taxText('Snapshot de 2025-11-30 (31 días antes del cierre): demasiado antiguo para afirmar el valor a 31/12 de ESTA partida; fuera del total.', 'en'))
      .toBe('Snapshot from 2025-11-30 (31 days before year end): too old to state THIS item\'s value on 31 Dec; left out of the total.');
    expect(taxText('Cuenta en USD (cartera «IBKR»)', 'en')).toBe('USD account (portfolio “IBKR”)');
    expect(taxText('Cuenta en USD', 'en')).toBe('USD account');
    expect(taxText('Falta la fecha de primera adquisición (obligatoria, posiciones 415-422) para: US0378331005, US5949181045. Aporta tax_declarant.first_acquisition_dates (ISIN → fecha YYYYMMDD).', 'en'))
      .toBe('The first acquisition date (mandatory, positions 415-422) is missing for: US0378331005, US5949181045. Provide the first acquisition dates (ISIN → date YYYYMMDD) in your declarant data.');
    expect(taxText('cash-USD', 'en')).toBe('USD cash');
    expect(taxText('Motivo nuevo con tax_declarant.custody', 'en')).toBe('Motivo nuevo con your declarant data');
  });

  it('en castellano no cambia nada', () => {
    const reason = data.templates.length ? 'Ubicación de la cuenta no declarada (la divisa no es el país). Declara tax_declarant.custody con la clave \'cash:USD\' en la metadata del tenant; mientras tanto, fuera del total.' : '';
    expect(taxText(reason, 'es')).toBe(humanizeTaxText(reason));
    expect(taxText('cash-USD', 'es')).toBe('caja USD');
  });

  it('la sección del 720 se pinta en inglés', () => {
    const thresholds = {
      fiscal_year: 2025,
      categories: {
        valores: { status: 'desconocido', total_base: 0, reasons: ['Sin snapshots de valoración a cierre del ejercicio: no se puede afirmar nada sobre esta categoría.'] },
        cuentas: { status: 'desconocido', total_base: 0, reasons: ['Sin snapshots de valoración a cierre del ejercicio: no se puede afirmar nada sobre esta categoría.'] },
      },
      unvalued: [{ ticker: 'PRB', reason: 'Posición actual sin snapshot de valoración a cierre del ejercicio: fuera del total, valorar a mano.' }],
      zero_balance_accounts: [{ account: 'Cuenta en USD (cartera «IBKR»)', reason: 'Saldo 0 a 31/12 y saldo medio del 4.º trimestre también 0: no suma nada al umbral de cuentas, por eso no se incluye en el total.' }],
    };
    const file720 = {
      available: false,
      reason: 'Faltan datos identificativos del declarante: el registro de tipo 1 exige NIF y apellidos y nombre, y no se inventan. Guárdalos en la metadata del tenant bajo la clave \'tax_declarant\' (nif, apellidos_nombre, numero_declaracion, custody_country, first_acquisition_dates...).',
    };
    const { container } = render(<LocaleProvider locale="en"><Modelo720Section thresholds={thresholds} file720={file720} /></LocaleProvider>);
    const text = container.textContent ?? '';
    expect(text).toContain('No valuation snapshots at year end: nothing can be stated about this category.');
    expect(text).toContain('PRB: Current position with no valuation snapshot at year end');
    expect(text).toContain('USD account (portfolio “IBKR”): Balance 0 on 31 Dec');
    expect(text).toContain('Declarant identification is missing');
    expect(text).not.toMatch(/Sin snapshots|Posición actual|Cuenta en|Faltan datos|metadata del tenant/);
  });
});
