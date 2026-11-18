import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProPick } from '@/lib/actions/proPicks.actions';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import MonthlyRebalanceView from '@/components/proPicks/MonthlyRebalanceView';
import { buildMonthlySnapshot } from '@/components/proPicks/monthlyRebalance';

const pick = (symbol: string, over: Record<string, unknown> = {}): ProPick =>
    ({
        symbol, company: `${symbol} Inc`, score: 75.4, grade: 'B+',
        categoryScores: { value: 60, growth: 70, profitability: 80, cashFlow: 65, momentum: 55, debtLiquidity: 50 },
        reasons: [], confidenceReasons: [], confidence: 72, confidenceLevel: 'Media', asOf: '2026-10-27',
        facts: { return12M: 12 }, ...over,
    }) as unknown as ProPick;

const snapshot = (over: Record<string, unknown> = {}) => ({
    ...buildMonthlySnapshot([pick('KEEP'), pick('GONE')], 'adaptive', '2026-08'),
    ...over,
});

function fileInput(container: HTMLElement): HTMLInputElement {
    return container.querySelector('input[type="file"]') as HTMLInputElement;
}

// jsdom no implementa File.text(): se define sobre la instancia.
async function upload(container: HTMLElement, content: string | undefined) {
    const input = fileInput(container);
    if (content === undefined) {
        fireEvent.change(input, { target: { files: [] } });
        return;
    }
    const file = new File([content], 'previo.json', { type: 'application/json' });
    Object.defineProperty(file, 'text', { value: async () => content });
    fireEvent.change(input, { target: { files: [file] } });
}

describe('MonthlyRebalanceView: sin historial', () => {
    it('la seleccion vigente se lista sin etiquetas Entra/Sale (aun no hay comparacion)', () => {
        render(<MonthlyRebalanceView currentPicks={[pick('AAA'), pick('BBB')]} month="2026-09" strategyId="adaptive" />);
        expect(screen.getByText('AAA')).toBeInTheDocument();
        expect(screen.getByText('BBB')).toBeInTheDocument();
        expect(screen.queryByText('Entra')).not.toBeInTheDocument();
        expect(screen.queryByText('Sale')).not.toBeInTheDocument();
    });
});

describe('MonthlyRebalanceView: carga del snapshot anterior', () => {
    it('un snapshot valido del mes anterior activa el diff: entran, salen y se mantienen', async () => {
        const { container } = render(
            <MonthlyRebalanceView currentPicks={[pick('KEEP'), pick('NEW')]} month="2026-09" strategyId="adaptive" />,
        );
        await upload(container, JSON.stringify(snapshot()));
        await waitFor(() => expect(screen.getAllByRole('heading', { level: 4 }).length).toBe(2));
        const lists = screen.getAllByRole('list');
        expect(within(lists[0]).getByText('NEW')).toBeInTheDocument(); // entra
        expect(within(lists[1]).getByText('GONE')).toBeInTheDocument(); // sale
        expect(within(lists[0]).getByText('Entra')).toBeInTheDocument();
        expect(within(lists[1]).getByText('Sale')).toBeInTheDocument();
        expect(screen.getByText('KEEP', { selector: 'span' })).toBeInTheDocument(); // se mantiene
        // el motivo de salida sin motivo guardado usa el texto por defecto
        expect(screen.getByText(/mes anterior/i)).toBeInTheDocument();
        // ya hay comparacion: desaparece el aviso de "sin historial"
        expect(screen.queryByText(/no guarda|no mantiene|history/i)).not.toBeInTheDocument();
    });

    it('con diff y sin altas ni bajas, cada grupo dice que esta vacio y no se listan mantenidos', async () => {
        const { container } = render(<MonthlyRebalanceView currentPicks={[]} month="2026-09" />);
        await upload(container, JSON.stringify(snapshot({ picks: [] })));
        await waitFor(() => expect(screen.getAllByRole('heading', { level: 4 }).length).toBe(2));
        expect(screen.queryAllByRole('list')).toHaveLength(0);
    });

    it('el motivo de salida usa el primer motivo guardado y la fuente (metrica y valor) cuando existen', async () => {
        const prev = snapshot({
            picks: [{
                symbol: 'GONE', company: 'Gone Inc', score: 1, confidence: 1, confidenceLevel: 'x', asOf: '',
                facts: {}, reasons: [{ text: 'Margen FCF 12 %', metric: 'fcf_margin', value: 12 }],
            }],
        });
        const { container } = render(<MonthlyRebalanceView currentPicks={[]} month="2026-09" />);
        await upload(container, JSON.stringify(prev));
        await waitFor(() => expect(screen.getByText('GONE')).toBeInTheDocument());
        expect(screen.getByText('Margen FCF 12 %')).toBeInTheDocument();
        expect(screen.getByTitle(/./)).toHaveTextContent(/fcf_margin/);
        expect(screen.getByTitle(/./)).toHaveTextContent(/12/);
    });

    it('un archivo que no es un snapshot muestra el error y no activa el diff', async () => {
        const { container } = render(<MonthlyRebalanceView currentPicks={[pick('A')]} month="2026-09" />);
        await upload(container, JSON.stringify({ kind: 'otra-cosa' }));
        await waitFor(() => expect(screen.getByText(/snapshot/i, { selector: 'p.text-red-400' })).toBeInTheDocument());
        expect(screen.getAllByRole('heading', { level: 4 })).toHaveLength(1); // sigue la seleccion vigente
    });

    it('JSON ilegible muestra el error de lectura', async () => {
        const { container } = render(<MonthlyRebalanceView currentPicks={[pick('A')]} month="2026-09" />);
        await upload(container, '{no es json');
        await waitFor(() => expect(document.querySelector('p.text-red-400')).not.toBeNull());
    });

    it('un snapshot de otra estrategia se rechaza con su motivo, y uno que no es anterior con otro distinto', async () => {
        const { container } = render(<MonthlyRebalanceView currentPicks={[pick('A')]} month="2026-09" strategyId="adaptive" />);
        await upload(container, JSON.stringify(snapshot({ strategyId: 'value' })));
        await waitFor(() => expect(document.querySelector('p.text-red-400')).not.toBeNull());
        const other = document.querySelector('p.text-red-400')!.textContent;
        await upload(container, JSON.stringify(snapshot({ month: '2026-09' })));
        await waitFor(() => expect(document.querySelector('p.text-red-400')!.textContent).not.toBe(other));
        expect(screen.getAllByRole('heading', { level: 4 })).toHaveLength(1);
    });

    it('sin archivo elegido (cancelar) limpia el error anterior sin cambiar nada', async () => {
        const { container } = render(<MonthlyRebalanceView currentPicks={[pick('A')]} month="2026-09" />);
        await upload(container, '{no es json');
        await waitFor(() => expect(document.querySelector('p.text-red-400')).not.toBeNull());
        await upload(container, undefined);
        await waitFor(() => expect(document.querySelector('p.text-red-400')).toBeNull());
    });

    it('«Cargar snapshot anterior» abre el selector de archivos', () => {
        const { container } = render(<MonthlyRebalanceView currentPicks={[pick('A')]} month="2026-09" />);
        const click = vi.spyOn(fileInput(container), 'click').mockImplementation(() => {});
        fireEvent.click(screen.getByRole('button', { name: /anterior|previous/i }));
        expect(click).toHaveBeenCalledTimes(1);
    });
});

describe('MonthlyRebalanceView: descarga y estados de los picks', () => {
    let createObjectURL: ReturnType<typeof vi.fn>;
    let revokeObjectURL: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        createObjectURL = vi.fn(() => 'blob:fake');
        revokeObjectURL = vi.fn();
        Object.assign(URL, { createObjectURL, revokeObjectURL });
    });
    afterEach(() => vi.restoreAllMocks());

    it('descargar genera el JSON del mes y la estrategia, con nombre de fichero propio', async () => {
        const anchors: HTMLAnchorElement[] = [];
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            anchors.push(this);
        });
        render(<MonthlyRebalanceView currentPicks={[pick('AAPL')]} month="2026-09" strategyId="value" />);
        fireEvent.click(screen.getByRole('button', { name: /Descargar|Download/i }));
        expect(createObjectURL).toHaveBeenCalledTimes(1);
        const blob = createObjectURL.mock.calls[0][0] as Blob;
        expect(blob.type).toBe('application/json');
        const text = await new Promise<string>((resolve) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result));
            reader.readAsText(blob);
        });
        const body = JSON.parse(text);
        expect(body).toMatchObject({ kind: 'cavaai-propicks-monthly-snapshot', month: '2026-09', strategyId: 'value' });
        expect(body.picks.map((p: { symbol: string }) => p.symbol)).toEqual(['AAPL']);
        expect(anchors).toHaveLength(1);
        expect(anchors[0].download).toBe('propicks-value-2026-09.json');
        expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake');
        expect(document.querySelector('a[download]')).toBeNull(); // el enlace temporal se retira
    });

    it('sin picks listos (cargando o error) no se puede descargar: boton deshabilitado y no se crea ningun blob', () => {
        const { rerender } = render(<MonthlyRebalanceView currentPicks={[]} month="2026-09" picksStatus="loading" />);
        const button = screen.getByRole('button', { name: /Descargar|Download/i });
        expect(button).toBeDisabled();
        fireEvent.click(button);
        rerender(<MonthlyRebalanceView currentPicks={[]} month="2026-09" picksStatus="error" />);
        expect(screen.getByRole('button', { name: /Descargar|Download/i })).toBeDisabled();
        expect(createObjectURL).not.toHaveBeenCalled();
    });

    it('error de picks: muestra el mensaje del servidor, o el generico si no hay, y no pinta ni el aviso de historial ni la seleccion', () => {
        const { rerender } = render(
            <MonthlyRebalanceView currentPicks={[]} month="2026-09" picksError="Fallo del backend" picksStatus="error" />,
        );
        expect(screen.getByText('Fallo del backend')).toBeInTheDocument();
        expect(screen.queryAllByRole('heading', { level: 4 })).toHaveLength(0);
        rerender(<MonthlyRebalanceView currentPicks={[]} month="2026-09" picksStatus="error" />);
        expect(screen.queryByText('Fallo del backend')).not.toBeInTheDocument();
        expect(document.querySelector('p.text-red-400')?.textContent?.length).toBeGreaterThan(0);
    });

    it('seleccion vigente vacia con picks listos: texto de vacio propio y sin lista', () => {
        render(<MonthlyRebalanceView currentPicks={[]} month="2026-09" />);
        expect(screen.queryAllByRole('list')).toHaveLength(0);
        expect(screen.getAllByRole('heading', { level: 4 })).toHaveLength(1);
    });

    it('nombre de estrategia propio y mes por defecto cuando no se pasa', () => {
        render(<MonthlyRebalanceView currentPicks={[pick('A')]} strategyName="Mi estrategia" />);
        expect(screen.getByText(/Mi estrategia/)).toBeInTheDocument();
        expect(screen.getByRole('heading', { level: 3 })).toBeInTheDocument();
    });
});
