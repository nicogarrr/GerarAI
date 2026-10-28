import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChangesSinceVisit } from '@/components/research/ChangesSinceVisit';
import { NewsSummary } from '@/components/research/NewsSummary';
import { ExternalNewsHeadline } from '@/components/research/ExternalNewsHeadline';
import { NewsHeadline } from '@/components/research/NewsHeadline';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => { vi.unstubAllGlobals(); window.localStorage.clear(); window.sessionStorage.clear(); });

describe('ChangesSinceVisit', () => {
    const payload = (over: Record<string, unknown> = {}) => ({
        since: '2026-10-01T10:00:00Z',
        documentos: { total: 5, items: [
            { titulo: 'Doc seguro', tipo: 'filing', url: 'https://sec.gov/a', fecha: null },
            { titulo: 'Doc http', tipo: 'filing', url: 'http://x.com/a', fecha: null },
            { titulo: 'Doc js', tipo: 'filing', url: 'javascript:alert(1)', fecha: null },
            { titulo: 'Doc cuarto', tipo: 'filing', url: null, fecha: null },
        ] },
        hechos: { total: 1, por_metrica: [{ metric: 'market_cap', n: 2 }] },
        cambios_tesis: [{ resumen: 'Cambio X.', direccion: 'neg', requiere_revision: true, fecha: '2026-10-02', fuente_url: 'https://news.com/x', fuente_nombre: 'Reuters',
            tambien_en: [{ url: 'https://b.com/x', fuente: 'Expansión' }, { url: 'http://mala.com', fuente: 'Mala' }] }],
        ...over,
    });
    let fetchMock: ReturnType<typeof vi.fn>;
    beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock); });

    it('primera visita (sin referencia): no pide nada ni pinta nada', async () => {
        const { container } = render(<ChangesSinceVisit ticker="AAPL" />);
        await Promise.resolve();
        expect(fetchMock).not.toHaveBeenCalled();
        expect(container).toBeEmptyDOMElement();
    });
    it('con visita previa pide los cambios desde esa fecha, con ticker codificado, y muestra el resumen', async () => {
        window.localStorage.setItem('cavaai:last-visit:BRK/B', '2026-10-01T10:00:00.000Z');
        fetchMock.mockResolvedValueOnce(json(payload()));
        render(<ChangesSinceVisit ticker="BRK/B" />);
        await screen.findByRole('region', { name: 'Cambios desde tu última visita' });
        const [url] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/companies/BRK%2FB/changes-since?since=2026-10-01T10%3A00%3A00.000Z');
        expect(screen.getByText(/5 documentos nuevos/)).toBeInTheDocument();
        expect(screen.getByText(/1 dato financiero nuevo/)).toBeInTheDocument();
        expect(screen.getByText(/Capitalización bursátil ×2/)).toBeInTheDocument();
        expect(screen.getByText(/requiere revisión/)).toBeInTheDocument();
        expect(screen.getByText(/y más/)).toBeInTheDocument();
    });
    it('solo enlaza URLs https (no http ni javascript:); el texto queda sin enlace', async () => {
        window.localStorage.setItem('cavaai:last-visit:AAPL', '2026-10-01T10:00:00.000Z');
        fetchMock.mockResolvedValueOnce(json(payload()));
        render(<ChangesSinceVisit ticker="AAPL" />);
        await screen.findByText(/Desde tu última visita/);
        const hrefs = screen.getAllByRole('link').map((a) => a.getAttribute('href'));
        expect(hrefs).toEqual(['https://sec.gov/a', 'https://news.com/x', 'https://b.com/x']);
        expect(screen.getByText(/Doc http/)).toBeInTheDocument();
        expect(screen.getByText(/Doc js/)).toBeInTheDocument();
        for (const a of screen.getAllByRole('link')) expect(a).toHaveAttribute('rel', 'noopener noreferrer');
    });
    it('sin novedades (todo a 0) no se pinta', async () => {
        window.localStorage.setItem('cavaai:last-visit:AAPL', '2026-10-01T10:00:00.000Z');
        fetchMock.mockResolvedValueOnce(json(payload({ documentos: { total: 0, items: [] }, hechos: { total: 0, por_metrica: [] }, cambios_tesis: [] })));
        const { container } = render(<ChangesSinceVisit ticker="AAPL" />);
        await waitFor(() => expect(fetchMock).toHaveBeenCalled());
        await act(async () => { await Promise.resolve(); });
        expect(container).toBeEmptyDOMElement();
    });
    it('error HTTP o red: no se inventa un diff', async () => {
        window.localStorage.setItem('cavaai:last-visit:AAPL', '2026-10-01T10:00:00.000Z');
        fetchMock.mockResolvedValueOnce(json({}, 500));
        const { container, unmount } = render(<ChangesSinceVisit ticker="AAPL" />);
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
        await act(async () => { await Promise.resolve(); });
        expect(container).toBeEmptyDOMElement();
        unmount();
        window.sessionStorage.clear();
        window.localStorage.setItem('cavaai:last-visit:AAPL', '2026-10-01T10:00:00.000Z');
        fetchMock.mockRejectedValueOnce(new Error('red'));
        const second = render(<ChangesSinceVisit ticker="AAPL" />);
        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
        await act(async () => { await Promise.resolve(); });
        expect(second.container).toBeEmptyDOMElement();
    });
    it('almacenamiento bloqueado: no falla ni pide nada', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
        const { container } = render(<ChangesSinceVisit ticker="AAPL" />);
        expect(container).toBeEmptyDOMElement();
        expect(fetchMock).not.toHaveBeenCalled();
    });
});

const ev = (over: Record<string, unknown> = {}) => ({
    id: 7, title: 'Titular', summary: 'The company reported strong quarterly earnings growth across all segments this year.', source: 'Reuters',
    headline_from_source: true, summary_translation: null, headline_translation: null, original_headline: null, ticker: 'AAPL', url: 'https://news.com/a', related_tickers: [], ...over,
}) as never;

describe('NewsSummary', () => {
    it('resumen en español: sin botón de traducir', () => {
        render(<NewsSummary event={ev({ summary: 'La compañía presentó unos resultados trimestrales sólidos en todos sus segmentos este año.' })} />);
        expect(screen.queryByRole('button', { name: 'Traducir' })).toBeNull();
    });
    it('titular no procedente de la fuente: no inventa resumen', () => {
        const { container } = render(<NewsSummary event={ev({ headline_from_source: false })} />);
        expect(container).toBeEmptyDOMElement();
    });
    it('traducción correcta: muestra el texto traducido y permite ver el original', async () => {
        const fetchMock = vi.fn().mockResolvedValueOnce(json({ status: 'translated', text: 'La empresa creció.' }));
        vi.stubGlobal('fetch', fetchMock);
        render(<NewsSummary event={ev()} />);
        fireEvent.click(screen.getByRole('button', { name: 'Traducir' }));
        await screen.findByText('La empresa creció.');
        expect(fetchMock.mock.calls[0][0]).toBe('/api/news/7/translation/summary');
        expect(fetchMock.mock.calls[0][1].method).toBe('POST');
        expect(screen.getByText(/Traducción automática/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Ver original' }));
        expect(screen.getByText(/The company reported/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Ver traducción' }));
        expect(screen.getByText('La empresa creció.')).toBeInTheDocument();
    });
    it.each([['quota', /por minuto/], ['budget', /Límite diario/], ['razon_nueva', /Traducción no disponible ahora mismo/]])('fallo %s: mensaje claro y el original se conserva', async (reason, text) => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({ status: 'failed', reason })));
        render(<NewsSummary event={ev()} />);
        fireEvent.click(screen.getByRole('button', { name: 'Traducir' }));
        expect(await screen.findByRole('status')).toHaveTextContent(text);
        expect(screen.getByText(/The company reported/)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Traducir' })).toBeEnabled();
    });
    it('error de red y HTTP 500 también acaban en mensaje genérico, no en silencio', async () => {
        vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('x')));
        const { unmount } = render(<NewsSummary event={ev()} />);
        fireEvent.click(screen.getByRole('button', { name: 'Traducir' }));
        expect(await screen.findByRole('status')).toHaveTextContent(/no disponible/);
        unmount();
        vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({}, 500)));
        render(<NewsSummary event={ev()} />);
        fireEvent.click(screen.getByRole('button', { name: 'Traducir' }));
        expect(await screen.findByRole('status')).toHaveTextContent(/no disponible/);
    });
    it('mientras traduce no permite doble envío', async () => {
        let resolve!: (r: Response) => void;
        const fetchMock = vi.fn(() => new Promise<Response>((r) => { resolve = r; }));
        vi.stubGlobal('fetch', fetchMock);
        render(<NewsSummary event={ev()} />);
        const button = screen.getByRole('button', { name: 'Traducir' });
        fireEvent.click(button);
        expect(screen.getByRole('button', { name: 'Traduciendo…' })).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Traduciendo…' }));
        expect(fetchMock).toHaveBeenCalledTimes(1);
        await act(async () => { resolve(json({ status: 'translated', text: 'ok' })); });
        await screen.findByText('ok');
    });
    it('traducción ya guardada se muestra sin pedirla', () => {
        render(<NewsSummary event={ev({ summary_translation: { text: 'Ya traducido' } })} />);
        expect(screen.getByText('Ya traducido')).toBeInTheDocument();
    });
});

type IOCallback = (entries: Array<{ isIntersecting: boolean }>) => void;
function stubIntersectionObserver() {
    const instances: Array<{ cb: IOCallback; disconnect: ReturnType<typeof vi.fn> }> = [];
    vi.stubGlobal('IntersectionObserver', class {
        disconnect = vi.fn();
        constructor(public cb: IOCallback) { instances.push(this as never); }
        observe() {}
    });
    return instances;
}

describe('ExternalNewsHeadline', () => {
    it('titular ya en español o muy corto: no pide traducción', () => {
        const io = stubIntersectionObserver();
        render(<ExternalNewsHeadline headline="La empresa presenta resultados récord del trimestre" />);
        expect(io).toHaveLength(0);
    });
    it('titular en inglés: se traduce al entrar en pantalla y se ofrece el original', async () => {
        const io = stubIntersectionObserver();
        const fetchMock = vi.fn().mockResolvedValue(json({ status: 'translated', text: 'Resultados récord' }));
        vi.stubGlobal('fetch', fetchMock);
        render(<ExternalNewsHeadline headline="Company posts record quarterly results in the market today unique-1" url="https://x.com/a" />);
        expect(fetchMock).not.toHaveBeenCalled();
        await act(async () => { io[0].cb([{ isIntersecting: false }]); });
        expect(fetchMock).not.toHaveBeenCalled();
        await act(async () => { io[0].cb([{ isIntersecting: true }]); });
        await screen.findByText('Resultados récord');
        expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ headline: 'Company posts record quarterly results in the market today unique-1' });
        expect(screen.getByText(/Traducción automática · ver original/)).toBeInTheDocument();
        expect(screen.getAllByRole('link')[0]).toHaveAttribute('href', 'https://x.com/a');
    });
    it('si la traducción falla se queda el original y se avisa de que no está traducido', async () => {
        const io = stubIntersectionObserver();
        vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('x')));
        render(<ExternalNewsHeadline headline="Another English headline about market results unique-2" />);
        await act(async () => { io[0].cb([{ isIntersecting: true }]); });
        await screen.findByText('Titular original (sin traducir)');
        expect(screen.getByText(/Another English headline/)).toBeInTheDocument();
    });
    it('titular de más de 500 caracteres no se manda a traducir y se avisa', () => {
        const io = stubIntersectionObserver();
        render(<ExternalNewsHeadline headline={`The company reported ${'very '.repeat(120)}strong results`} />);
        expect(io).toHaveLength(0);
        expect(screen.getByText('Titular original (sin traducir)')).toBeInTheDocument();
    });
});

describe('NewsHeadline', () => {
    it('titular traducido guardado: lo muestra con aviso y el original en desplegable', () => {
        stubIntersectionObserver();
        render(<NewsHeadline event={ev({ headline_translation: { text: 'Titular traducido' }, original_headline: 'Original headline' })} />);
        expect(screen.getByText('Titular traducido')).toBeInTheDocument();
        expect(screen.getByText('Traducción automática · español')).toBeInTheDocument();
        expect(screen.getByText('Original headline')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Titular traducido' })).toHaveAttribute('href', 'https://news.com/a');
    });
    it('traduce al hacerse visible y fija el resultado', async () => {
        const io = stubIntersectionObserver();
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ status: 'translated', text: 'Hola mundo' })));
        render(<NewsHeadline event={ev({ id: 99, title: 'Strong earnings beat expectations for the quarter', url: null })} />);
        await act(async () => { io[0].cb([{ isIntersecting: true }]); });
        await screen.findByText('Hola mundo');
        expect(io[0].disconnect).toHaveBeenCalled();
    });
    it('si la fuente no dio titular real no se intenta traducir', () => {
        const io = stubIntersectionObserver();
        render(<NewsHeadline event={ev({ headline_from_source: false })} />);
        expect(io).toHaveLength(0);
    });
});
