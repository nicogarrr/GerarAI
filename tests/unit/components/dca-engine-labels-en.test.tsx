import React from 'react';
import { readFileSync } from 'node:fs';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import { dcaEngineText } from '@/lib/dca/engine-text';
import { LocaleProvider } from '@/lib/i18n/client';
import { createTranslator } from '@/lib/i18n/translate';
import type { DcaSignalItem } from '@/lib/dca/types';

// Etiquetas reales del motor, leídas de los .py: si cambian, el test lo nota.
const ENGINE = readFileSync('data-engine/app/services/dca_signal_engine.py', 'utf8');
const ZONES = [...ENGINE.matchAll(/"label": "([^"]+)", "zone": "([^"]+)"/g)].map((m) => ({ label: m[1], zone: m[2] }));
const GROUPS = [...ENGINE.matchAll(/\("[\dx-]+", "([^"]+)", \(/g)].map((m) => m[1]);
const BACKTEST = readFileSync('data-engine/app/services/dca_backtest.py', 'utf8');
const PLANS = [...BACKTEST.matchAll(/_plan_summary\(\s*"\w+",\s*"([^"]+)"/g)].map((m) => m[1]);

const en = createTranslator('en');
const es = createTranslator('es');
const SPANISH = /RECORTE|Zona|compra|aportaci|recorte|Todos|plano|niveles|Niveles|presupuesto/;

describe('DCA: etiquetas del motor en el idioma de la pantalla', () => {
    it('lee las 6 zonas, los 4 grupos de aciertos y los 3 planes del backtest', () => {
        expect(ZONES).toHaveLength(6);
        expect(GROUPS).toEqual(['Todos 2X–4X', '4X DCA', '3X DCA', '2X DCA']);
        expect(PLANS).toHaveLength(3);
    });

    it('en inglés, ninguna sale en castellano', () => {
        const all = [...ZONES.flatMap((z) => [z.label, z.zone]), ...GROUPS, ...PLANS];
        for (const text of all) expect(dcaEngineText(text, en)).not.toMatch(SPANISH);
        expect(ZONES.map((z) => dcaEngineText(z.label, en))).toEqual(['4X DCA', '3X DCA', '2X DCA', '1X DCA', 'LIGHT TRIM', 'STRONG TRIM']);
        expect(dcaEngineText(GROUPS[0], en)).toBe('All 2X–4X');
        expect(PLANS.map((p) => dcaEngineText(p, en))).toEqual(['Plain DCA', 'Level-based DCA (adds extra)', 'Levels with fixed budget']);
    });

    it('en castellano, conserva las etiquetas y corrige la tilde antigua', () => {
        const all = [...ZONES.flatMap((z) => [z.label, z.zone]), ...GROUPS, ...PLANS];
        expect(all.map((text) => dcaEngineText(text, es))).toEqual(all.map((text) => text === 'Zona de aportacion normal' ? 'Zona de aportación normal' : text));
    });

    it('traduce la zona normal antigua y corregida sin perder otros textos', () => {
        expect(dcaEngineText('Zona de aportacion normal', en)).toBe('Normal contribution zone');
        expect(dcaEngineText('Zona de aportación normal', en)).toBe('Normal contribution zone');
        expect(dcaEngineText('Zona de aportacion normal', es)).toBe('Zona de aportación normal');
        expect(dcaEngineText('Unknown zone', en)).toBe('Unknown zone');
    });

    it('el distintivo de la watchlist en inglés: nivel y zona en inglés', async () => {
        const trim = ZONES.find((z) => z.label.startsWith('RECORTE'))!;
        const item = {
            symbol: 'UBER', company_name: 'Uber', sources: ['watchlist'], in_watchlist: true, in_portfolio: false,
            min_level_override: null, effective_min_level: 2, alerts_on: true,
            state: {
                key: 'light-trim', label: trim.label, zone: trim.zone, color: '#FF9F0A', fg: '#000000', level: -1, previous_level: 1,
                status: 'confirmed', period: '2026-09', signal_date: '2026-09-30', close: 70, currency: 'USD', currency_label: 'USD',
                metrics: {}, level_prices: {}, params_version: 'v1', data_source: 'yahoo',
                evaluated_at: '2026-10-27T22:00:00Z', last_alerted_level: -1, last_alerted_period: '2026-09',
            },
        } as unknown as DcaSignalItem;
        render(<LocaleProvider locale="en"><DcaLevelBadge item={item} signalMonths={30} compact /></LocaleProvider>);
        const badge = screen.getByRole('button', { name: /UBER: LIGHT TRIM/ });
        expect(badge.textContent).not.toMatch(SPANISH);
        fireEvent.pointerDown(badge, { pointerType: 'touch' });
        fireEvent.click(badge);
        expect((await screen.findAllByText('Light trim zone')).length).toBeGreaterThan(0);
    });
});
