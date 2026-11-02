import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MacroEventRow } from '@/components/calendar/MacroEventRow';
import type { MacroEvent } from '@/lib/actions/macro-calendar.actions';
import { macroSourceName } from '@/lib/calendar/macro-text';
import { createTranslator } from '@/lib/i18n/translate';

// Textos reales que manda macro_calendar_service.py (leídos del .py: si el
// backend los cambia, este test lo nota).
const PY = readFileSync('data-engine/app/services/macro_calendar_service.py', 'utf8');
const pyString = (re: RegExp): string => {
    const m = PY.match(re);
    if (!m) throw new Error(`no encontrado en macro_calendar_service.py: ${re}`);
    return m[1];
};
const BLS = Object.fromEntries(
    [...PY.matchAll(/\("(cpi|employment|ppi|jolts|eci)", "([^"]+)"\)/g)].map((m) => [m[1], m[2]]),
) as Record<string, string>;
const FOMC_TITLE = pyString(/title = "(Reunión del FOMC[^"]*)"/);
const FOMC_DETAIL = pyString(/"detail": "([^"]+)" if raw\["projections"\]/);
const FOMC_SOURCE = pyString(/run\("(Reserva Federal[^"]*)"/);

const enT = createTranslator('en');

function event(kind: string, title: string, detail: string | null): MacroEvent {
    return {
        kind, date: '2026-12-09', start_date: '2026-12-08', time_et: null, title, detail,
        source: 'Reserva Federal', source_url: 'https://www.federalreserve.gov/', label: 'OFICIAL',
    } as MacroEvent;
}

describe('calendario macro en inglés (textos reales del backend)', () => {
    it('lee del backend los 6 títulos, el detalle y la fuente', () => {
        expect(Object.keys(BLS).sort()).toEqual(['cpi', 'eci', 'employment', 'jolts', 'ppi']);
        expect(FOMC_TITLE).toBe('Reunión del FOMC (decisión de tipos)');
        expect(FOMC_DETAIL).toBe('Con proyecciones económicas');
        expect(FOMC_SOURCE).toBe('Reserva Federal (FOMC)');
    });

    it('en inglés, la reunión del FOMC y su detalle salen en inglés', () => {
        render(<ul><MacroEventRow event={event('fomc', FOMC_TITLE, FOMC_DETAIL)} dateLabel="Dec 9, 2026" ti={enT} locale="en" /></ul>);
        expect(screen.getByText(/FOMC meeting \(rate decision\)/)).toBeInTheDocument();
        expect(screen.getByText(/With economic projections/)).toBeInTheDocument();
        expect(screen.queryByText(/Reunión|proyecciones/)).toBeNull();
    });

    it.each([
        ['cpi', 'US CPI (inflation)'],
        ['employment', 'US jobs report'],
        ['ppi', 'US PPI (producer prices)'],
        ['jolts', 'JOLTS: job openings'],
        ['eci', 'Employment Cost Index'],
    ])('en inglés, %s sale como «%s»', (kind, english) => {
        render(<ul><MacroEventRow event={event(kind, BLS[kind], null)} dateLabel="Dec 9, 2026" ti={enT} locale="en" /></ul>);
        expect(screen.getByText(english)).toBeInTheDocument();
        expect(screen.queryByText(BLS[kind])).toBeNull();
    });

    it('un título que el frontend no conoce pasa tal cual', () => {
        render(<ul><MacroEventRow event={event('gdp', 'PIB de EE. UU.', null)} dateLabel="Dec 9, 2026" ti={enT} locale="en" /></ul>);
        expect(screen.getByText('PIB de EE. UU.')).toBeInTheDocument();
    });

    it('en castellano todo pasa tal cual', () => {
        render(<ul><MacroEventRow event={event('fomc', FOMC_TITLE, FOMC_DETAIL)} dateLabel="9 dic 2026" /></ul>);
        expect(screen.getByText(FOMC_TITLE)).toBeInTheDocument();
        expect(screen.getByText(/Con proyecciones económicas/)).toBeInTheDocument();
    });

    it('el aviso de fuente caída nombra la fuente en inglés', () => {
        expect(macroSourceName(FOMC_SOURCE, 'en')).toBe('Federal Reserve (FOMC)');
        expect(macroSourceName('BLS', 'en')).toBe('BLS');
        expect(macroSourceName(FOMC_SOURCE, 'es')).toBe(FOMC_SOURCE);
    });
});
