import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { QuickGlancePanel } from '@/components/research/QuickGlancePanel';
import type { ManagementCredibility } from '@/components/research/sections/ManagementCredibilitySection';
import type { ShareCapital } from '@/lib/actions/share-capital.actions';
import type { MoatScoreMetric, ResearchLongTermModel } from '@/lib/actions/research.actions';
import type { AnalystTargets } from '@/lib/research/analyst-targets';

const model = (over: Record<string, unknown> = {}) =>
    ({
        status: 'generated',
        publishable: true,
        as_of_period: 'FY2025',
        scenarios: { base: { valuation: { value_per_share: 123.45 } } },
        ...over,
    }) as unknown as ResearchLongTermModel;

const analysts = (over: Record<string, unknown> = {}) =>
    ({
        status: 'available',
        consensus: { median: 150 },
        currency: 'USD',
        fetched_at: 0,
        rows: [],
        source: 'Yahoo Finance (no oficial), agregado de analistas',
        symbol: 'TEST',
        ...over,
    }) as unknown as AnalystTargets;

const shareCapital = (over: Record<string, unknown> = {}) =>
    ({
        ticker: 'TEST',
        status: 'OFICIAL',
        as_of: '2025-12-31',
        share_basis: 'reported_unadjusted',
        series: [],
        annual_flows: [{ date: '2024-12-31', shares_repurchased: { value: 1000 } }],
        ...over,
    }) as unknown as ShareCapital;

const credibility = (over: Record<string, unknown> = {}) =>
    ({
        ticker: 'TEST',
        score: 0.8,
        grade: 'high',
        counts: { total: 5, open: 2, met: 3, partial: 0, missed: 0 },
        ...over,
    }) as unknown as ManagementCredibility;

const moat = (score: number | null) =>
    ({ calculation_trace: score === null ? {} : { score } }) as unknown as MoatScoreMetric;

const base = {
    ticker: 'TEST',
    currency: 'USD',
    model: model(),
    analysts: analysts(),
    livePrice: 100,
    shareCapital: shareCapital(),
    credibility: credibility(),
    moatScore: moat(72),
};

describe('QuickGlancePanel', () => {
    it('pinta cada fila con dato real enlazada a su sección', () => {
        render(<QuickGlancePanel {...base} />);
        expect(screen.getByRole('heading', { name: 'Vistazo rápido' })).toBeVisible();
        expect(screen.getByRole('link', { name: /Valor del modelo \(datos a FY2025\)/ }))
            .toHaveAttribute('href', '/research/TEST?view=valoracion#modelo');
        expect(screen.getByText('123,45 US$')).toBeVisible();
        expect(screen.getByRole('link', { name: /Recompras \(registros SEC\)/ }))
            .toHaveAttribute('href', '/research/TEST?view=finanzas#dilucion');
        expect(screen.getByText('Sí, en 2024')).toBeVisible();
        expect(screen.getByRole('link', { name: /Compromisos de la directiva/ }))
            .toHaveAttribute('href', '/research/TEST?view=seguimiento#directiva');
        expect(screen.getByText(/2 abiertas por comprobar/)).toBeVisible();
        expect(screen.getByRole('link', { name: /Calidad financiera \(marco de foso\)/ }))
            .toHaveAttribute('href', '/research/TEST?view=valoracion#foso');
        expect(screen.getByText('72/100')).toBeVisible();
    });

    it('etiqueta el consenso como agregado Yahoo no oficial con su recorrido', () => {
        render(<QuickGlancePanel {...base} />);
        expect(screen.getByRole('link', { name: /Analistas \(agregado Yahoo, no oficial\)/ }))
            .toHaveAttribute('href', '#analistas');
        expect(screen.getByText('Mediana 150,00 US$')).toBeVisible();
        // Recorrido de la mediana contra el precio en vivo: (150-100)/100 = +50 %.
        expect(screen.getByText(/Recorrido a la mediana: \+50,0 %/)).toBeVisible();
    });

    it('sin recorrido cuando falta el precio en vivo (nada inventado)', () => {
        render(<QuickGlancePanel {...base} livePrice={null} />);
        expect(screen.getByText('Mediana 150,00 US$')).toBeVisible();
        expect(screen.queryByText(/Recorrido a la mediana/)).toBeNull();
    });

    it('no pinta filas sin dato real', () => {
        const { rerender } = render(
            <QuickGlancePanel {...base} model={model({ publishable: false })} />,
        );
        expect(screen.queryByText(/Valor del modelo/)).toBeNull();

        rerender(<QuickGlancePanel {...base} model={model({ status: 'not_generated' })} />);
        expect(screen.queryByText(/Valor del modelo/)).toBeNull();

        rerender(<QuickGlancePanel {...base} analysts={analysts({ status: 'unavailable' })} />);
        expect(screen.queryByText(/Analistas/)).toBeNull();

        rerender(<QuickGlancePanel {...base} analysts={analysts({ consensus: { median: null } })} />);
        expect(screen.queryByText(/Analistas/)).toBeNull();

        rerender(<QuickGlancePanel {...base} shareCapital={shareCapital({ status: 'SIN_DATOS' })} />);
        expect(screen.queryByText(/Recompras/)).toBeNull();

        rerender(<QuickGlancePanel {...base} credibility={null} />);
        expect(screen.queryByText(/Compromisos de la directiva/)).toBeNull();

        rerender(<QuickGlancePanel {...base} moatScore={moat(null)} />);
        expect(screen.queryByText(/Calidad financiera/)).toBeNull();
    });

    it('declara sin recompras cuando el registro SEC oficial no recoge ninguna', () => {
        render(<QuickGlancePanel {...base} shareCapital={shareCapital({ annual_flows: [] })} />);
        expect(screen.getByText('Sin recompras declaradas')).toBeVisible();
    });

    it('devuelve null cuando ninguna fila tiene dato', () => {
        const { container } = render(
            <QuickGlancePanel
                ticker="TEST"
                currency="USD"
                model={null}
                analysts={null}
                livePrice={null}
                shareCapital={null}
                credibility={null}
                moatScore={null}
            />,
        );
        expect(container).toBeEmptyDOMElement();
        expect(screen.queryByText('Vistazo rápido')).toBeNull();
    });
});
