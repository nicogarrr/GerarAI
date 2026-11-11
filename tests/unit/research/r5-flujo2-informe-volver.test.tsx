import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import { inAppHistoryStore } from '@/lib/nav/in-app-history';
import type { ReportInputs } from '@/lib/research/analyst-report';
import fixture from './analyst-report-asts.fixture.json';

// Auditoría de flujo r5 (11-nov): «← Volver a la ficha» del Informe iba
// siempre a /research/T, sin la pestaña `?view=` de la que se venía y arriba
// del todo. Usa ya el enlace de vuelta por historial de #5382.
const data: ReportInputs = { ...(fixture as unknown as ReportInputs), card: null, fair: null, thesis: null, sotp: null, engineRange: null, consensus: { cells: [] } };
const view = () => <AnalystReportView data={data} t={createTranslator('es')} fmt={createFormatters('es')} locale="es" />;
const ticker = (fixture as unknown as { ticker: string }).ticker;

describe('Informe: «Volver a la ficha»', () => {
    let back: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
        inAppHistoryStore.reset();
        back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
    });
    afterEach(() => back.mockRestore());

    it('llegando desde la ficha (pestaña Valoración) vuelve por historial', () => {
        inAppHistoryStore.record(`/research/${ticker}?view=valoracion`);
        inAppHistoryStore.record(`/research/${ticker}/informe`);
        render(view());
        const link = screen.getByRole('link', { name: '← Volver a la ficha' });
        expect(link).toHaveAttribute('data-back-mode', 'history');
        fireEvent.click(link);
        expect(back).toHaveBeenCalledTimes(1);
    });

    it('abierto directamente (enlace de Telegram) sigue siendo un enlace a la ficha', () => {
        inAppHistoryStore.record(`/research/${ticker}/informe`);
        render(view());
        const link = screen.getByRole('link', { name: '← Volver a la ficha' });
        expect(link).toHaveAttribute('href', `/research/${encodeURIComponent(ticker)}`);
        expect(link).toHaveAttribute('data-back-mode', 'link');
        fireEvent.click(link);
        expect(back).not.toHaveBeenCalled();
    });
});
