import { readFileSync } from 'node:fs';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { getGems, reviewGems, getDeepValue, getTrackRecord } = vi.hoisted(() => ({
    getGems: vi.fn(), reviewGems: vi.fn(), getDeepValue: vi.fn(), getTrackRecord: vi.fn(),
}));
vi.mock('@/lib/actions/propicks-gems.actions', () => ({ getGems, reviewGems }));
vi.mock('@/lib/actions/propicks-deep-value.actions', () => ({ getDeepValue }));
vi.mock('@/lib/actions/propicks-track-record.actions', () => ({ getTrackRecord }));

import GemsView from '@/components/proPicks/GemsView';
import DeepValueView from '@/components/proPicks/DeepValueView';
import TrackRecordView from '@/components/proPicks/TrackRecordView';
import { LocaleProvider } from '@/lib/i18n/client';
import en from '@/lib/i18n/messages/en/propicks.json';

// Frases REALES que devuelven las acciones de servidor al fallar (siempre en castellano).
const real = (file: string) => [...readFileSync(`lib/actions/${file}.actions.ts`, 'utf8').matchAll(/error: '([^']+)'/g)].map((m) => m[1]);
const [GEMS_LOAD] = real('propicks-gems');
const [DEEP_LOAD] = real('propicks-deep-value');
const [TRACK_LOAD] = real('propicks-track-record');

const inEnglish = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

describe('Pro Picks: errores de carga en el idioma elegido', () => {
    it('las frases de prueba son las de las acciones', () => {
        expect([GEMS_LOAD, DEEP_LOAD, TRACK_LOAD]).toEqual([
            'No se pudieron cargar las joyas.',
            'No se pudo cargar el cribado deep value.', 'No se pudo cargar el histórico de selecciones.',
        ]);
    });
    it('joyas en inglés: carga', async () => {
        getGems.mockResolvedValue({ error: GEMS_LOAD });
        const { container } = inEnglish(<GemsView />);
        await waitFor(() => expect(screen.getByText(en.gems.loadError)).toBeTruthy());
        expect(container.textContent).not.toContain(GEMS_LOAD);
    });
    it('deep value en inglés', async () => {
        getDeepValue.mockResolvedValue({ error: DEEP_LOAD });
        const { container } = inEnglish(<DeepValueView />);
        await waitFor(() => expect(screen.getByText(en.deepValue.loadError)).toBeTruthy());
        expect(container.textContent).not.toContain(DEEP_LOAD);
    });
    it('histórico de selecciones en inglés', async () => {
        getTrackRecord.mockResolvedValue({ error: TRACK_LOAD });
        const { container } = inEnglish(<TrackRecordView />);
        await waitFor(() => expect(screen.getByText(en.trackRecord.loadError)).toBeTruthy());
        expect(container.textContent).not.toContain(TRACK_LOAD);
    });
    it('en castellano, la misma frase de siempre', async () => {
        getGems.mockResolvedValue({ error: GEMS_LOAD });
        getDeepValue.mockResolvedValue({ error: DEEP_LOAD });
        getTrackRecord.mockResolvedValue({ error: TRACK_LOAD });
        render(<><GemsView /><DeepValueView /><TrackRecordView /></>);
        for (const text of [GEMS_LOAD, DEEP_LOAD, TRACK_LOAD]) await waitFor(() => expect(screen.getByText(text)).toBeTruthy());
    });
});
